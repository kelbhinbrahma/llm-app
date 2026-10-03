# The FastAPI application: all the API endpoints are here.
#
#   POST /auth/login       -> get a JWT token
#   POST /chat             -> ask a question, get an LLM answer (needs token, role admin/user)
#   GET  /health           -> is the app, database and Redis OK?
#   GET  /metrics          -> Prometheus metrics (needs token, role admin)
#   GET  /reports/usage    -> usage per user from the database (role admin/readonly)
#
# Run locally:  uvicorn app.main:app --reload     Docs page: http://localhost:8000/docs

import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app import auth, cache, config, llm, metrics
from app.database import ChatLog, SessionLocal, User, create_tables, get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")


# ---------- startup ----------

def create_demo_users():
    # Creates one user per role, only if the password is set in the environment.
    demo_users = [
        ("admin", config.ADMIN_PASSWORD, "admin"),
        ("alice", config.USER_PASSWORD, "user"),
        ("viewer", config.READONLY_PASSWORD, "readonly"),
    ]
    db = SessionLocal()
    try:
        for username, password, role in demo_users:
            if not password:
                continue
            exists = db.query(User).filter(User.username == username).first()
            if not exists:
                db.add(User(username=username, password_hash=auth.hash_password(password), role=role))
                logger.info("Created demo user %s (%s)", username, role)
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app):
    # Runs once when the app starts.
    if not config.JWT_SECRET:
        raise RuntimeError("JWT_SECRET is not set. Copy .env.example to .env and fill it in.")
    # When several app instances start together they may all try to create the
    # tables at the same moment, or the database may still be starting.
    # So we simply try a few times.
    for attempt in range(1, 6):
        try:
            create_tables()
            create_demo_users()
            break
        except Exception as error:
            logger.warning("Database setup failed (attempt %s): %s", attempt, error)
            if attempt == 5:
                raise
            time.sleep(2)
    yield


app = FastAPI(title="AI Question-Answering API", version="1.0.0", lifespan=lifespan)


# ---------- middleware: record latency of every request ----------

@app.middleware("http")
async def record_metrics(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    seconds = time.perf_counter() - start
    path = request.url.path
    metrics.REQUEST_LATENCY.labels(path=path).observe(seconds)
    metrics.REQUESTS.labels(method=request.method, path=path, status=response.status_code).inc()
    return response


# ---------- request / response shapes (Pydantic validates them for us) ----------

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    answer: str
    model: str
    cached: bool
    prompt_tokens: int
    answer_tokens: int
    latency_ms: int


# ---------- endpoints ----------

@app.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if user is None or not auth.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong username or password")
    token = auth.create_token(user.username, user.role)
    return LoginResponse(access_token=token, role=user.role)


@app.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    user=Depends(auth.require_permission("chat")),
    db: Session = Depends(get_db),
):
    start = time.perf_counter()
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty")

    # 1. rate limit (Redis)
    if cache.is_rate_limited(user["username"]):
        raise HTTPException(status_code=429, detail="Too many requests, try again in a minute")

    # 2. cache (Redis)
    result = cache.get_cached_answer(question)
    cached = result is not None
    if cached:
        metrics.CACHE_HITS.inc()
        prompt_tokens, answer_tokens = 0, 0  # no LLM call -> no tokens used
    else:
        # 3. call the LLM (with retry + fallback inside ask_llm)
        llm_start = time.perf_counter()
        try:
            result = llm.ask_llm(question)
        except llm.LLMError:
            metrics.LLM_ERRORS.inc()
            raise HTTPException(status_code=503, detail="LLM service is unavailable, please try again later")
        metrics.LLM_LATENCY.observe(time.perf_counter() - llm_start)
        prompt_tokens, answer_tokens = result["prompt_tokens"], result["answer_tokens"]
        metrics.LLM_TOKENS.labels(type="prompt").inc(prompt_tokens)
        metrics.LLM_TOKENS.labels(type="answer").inc(answer_tokens)
        cache.save_answer(question, result)

    latency_ms = int((time.perf_counter() - start) * 1000)

    # 4. save a log row in PostgreSQL
    db.add(
        ChatLog(
            username=user["username"],
            question=question,
            answer=result["answer"],
            model=result["model"],
            cached=1 if cached else 0,
            prompt_tokens=prompt_tokens,
            answer_tokens=answer_tokens,
            latency_ms=latency_ms,
        )
    )
    db.commit()

    return ChatResponse(
        answer=result["answer"],
        model=result["model"],
        cached=cached,
        prompt_tokens=prompt_tokens,
        answer_tokens=answer_tokens,
        latency_ms=latency_ms,
    )


@app.get("/health")
def health(response: Response):
    # Used by Docker / load balancer to know if this instance is alive.
    db_ok = True
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
    except Exception:
        db_ok = False

    redis_ok = cache.redis_is_up()

    # The database is required; Redis is optional (the app degrades without it).
    if not db_ok:
        response.status_code = 503
    return {
        "status": "ok" if db_ok else "error",
        "database": "up" if db_ok else "down",
        "redis": "up" if redis_ok else "down",
    }


@app.get("/metrics")
def get_metrics(user=Depends(auth.require_permission("view_metrics"))):
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/reports/usage")
def usage_report(
    user=Depends(auth.require_permission("view_reports")),
    db: Session = Depends(get_db),
):
    # Same as: SELECT username, COUNT(*), SUM(prompt_tokens + answer_tokens), AVG(latency_ms)
    #          FROM chat_logs GROUP BY username;
    rows = (
        db.query(
            ChatLog.username,
            func.count(ChatLog.id),
            func.sum(ChatLog.prompt_tokens + ChatLog.answer_tokens),
            func.avg(ChatLog.latency_ms),
        )
        .group_by(ChatLog.username)
        .all()
    )
    return [
        {
            "username": username,
            "requests": count,
            "total_tokens": int(tokens or 0),
            "avg_latency_ms": round(float(avg or 0), 1),
        }
        for username, count, tokens, avg in rows
    ]
