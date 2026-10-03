# Learning Guide: how this project works, step by step

This guide assumes you know **Python and SQL** and nothing else. It explains every tool and term in the
project in the order you would learn them, and shows where each one lives in the code.

Read it in order. Each part ends with "Try it" so you can see the idea working.

---

## Part 0: The big picture in plain words

A user sends a question. Our program:

1. checks who they are (login + token),
2. checks they haven't asked too many questions this minute,
3. looks for a saved answer to the same question,
4. if none, asks Google's Gemini AI, trying again if it fails,
5. saves what happened (time taken, tokens used) and sends the answer back.

Everything else (Docker, nginx, Redis, PostgreSQL, Prometheus) exists so that this works for **many users**,
**safely**, and so we can **see** what's happening.

---

## Part 1: APIs, HTTP and JSON

**API (Application Programming Interface)**: a way for one program to talk to another. A **web API** does it
over the internet using HTTP. Our API is a program that waits for requests and sends back answers.

**HTTP request** has:
- a **method**: `GET` (read something), `POST` (send something / do something)
- a **path** (also called endpoint or route): `/chat`, `/health`
- **headers**: extra info, e.g. `Authorization: Bearer <token>`, `Content-Type: application/json`
- a **body**: the data, usually JSON

**JSON**: text format for data, looks like a Python dict: `{"question": "What is Docker?"}`

**HTTP status codes** (the number in every response):

| Code | Meaning | In this project |
|---|---|---|
| 200 | OK | Answer returned |
| 401 | Unauthorized: we don't know who you are | No token, bad token, wrong password |
| 403 | Forbidden: we know you, but you're not allowed | `readonly` user calls `/chat` |
| 422 | Unprocessable: your data is wrong | Empty question |
| 429 | Too Many Requests | Rate limit hit |
| 503 | Service Unavailable | Gemini failed every time |

**curl**: a command-line tool to send HTTP requests. `curl http://localhost:8000/health`

---

## Part 2: FastAPI (the web framework)

**Framework**: a library that does the boring parts (listening on a port, reading HTTP, making JSON) so you
only write the logic.

**FastAPI** turns normal Python functions into API endpoints:

```python
app = FastAPI()

@app.get("/health")          # decorator: "when someone does GET /health, run this"
def health():
    return {"status": "ok"}  # FastAPI converts the dict to JSON
```

**Uvicorn**: the **server** that actually runs the FastAPI app and listens on a port.
`uvicorn app.main:app --reload` means "in file `app/main.py`, run the object called `app`, and reload on code changes".
`--workers 2` starts 2 processes so two CPU cores can be used.

**Pydantic models**: classes that describe the shape of the JSON. FastAPI checks incoming data
automatically and returns **422** if it's wrong.

```python
class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
```

**Dependency injection (`Depends`)**: a way to say "before running this endpoint, run that function and give
me its result". We use it for: getting a database session (`get_db`) and checking the token
(`require_permission("chat")`). If the dependency raises an error, the endpoint never runs.

**Middleware**: code that runs around **every** request. Ours (`record_metrics`) starts a timer, lets the
request run, then records how long it took.

**Swagger UI / OpenAPI**: FastAPI auto-generates a documentation page at `/docs` where you can try every
endpoint in the browser. Click "Authorize" and paste your token to call protected endpoints.

**Lifespan**: code that runs once when the app starts (we create tables and demo users there).

**sync vs async**: `def` endpoints run in a **thread pool** (FastAPI runs many at once in threads).
`async def` endpoints run on an **event loop**, which can wait on thousands of network calls with one thread.
I used plain `def` because it's simpler and my LLM library call is blocking; switching to async is the
first production improvement (see ARCHITECTURE.md).

Where: `app/main.py`

Try it: run `uvicorn app.main:app --reload`, open http://localhost:8000/docs

---

## Part 3: Environment variables and configuration

**Hard-coding a secret** = writing a password or API key in the code. Anyone who sees the code (GitHub!)
gets the secret. Never do it.

**Environment variables**: values set outside the program, read with `os.getenv("NAME")`.
**`.env` file**: a local file with `NAME=value` lines. `python-dotenv` loads it into the environment.
`.env` is in `.gitignore` so it never goes to Git. `.env.example` shows which variables exist, with
dummy values, and *is* committed.

**12-factor app**: a well-known set of rules for cloud apps; one rule is "store config in the environment".
The same Docker image then runs in dev, test and production with different settings.

Where: `app/config.py`, `.env.example`

---

## Part 4: Databases with SQLAlchemy

You know SQL. **PostgreSQL** is a SQL database server (like MySQL). We store:

- `users`: username, hashed password, role
- `chat_logs`: every question with answer, model, tokens, latency, time

**ORM (Object Relational Mapper)**: lets you use Python classes instead of writing SQL by hand.
**SQLAlchemy** is the most common Python ORM.

| SQL | SQLAlchemy |
|---|---|
| `CREATE TABLE users (...)` | `class User(Base): ...` + `Base.metadata.create_all()` |
| `INSERT INTO chat_logs ...` | `db.add(ChatLog(...)); db.commit()` |
| `SELECT * FROM users WHERE username = 'alice'` | `db.query(User).filter(User.username == "alice").first()` |
| `SELECT username, COUNT(*) ... GROUP BY username` | `db.query(ChatLog.username, func.count(ChatLog.id)).group_by(...)` |

Why use it: the same code works on PostgreSQL (Docker) and SQLite (tests), and it uses **parameterised
queries**, which prevents **SQL injection** (a user typing SQL into an input to attack the DB).

**Engine**: the connection to the database. **Session**: one "conversation" with the DB (one per request).
**Connection pool**: the engine keeps a few connections open and reuses them, because opening a new one is slow.
`pool_pre_ping=True` checks a connection still works before using it.

**Connection string / URL**: `postgresql+psycopg2://user:password@host:5432/dbname`.
`psycopg2` is the driver (the library that actually speaks to Postgres).

**Migrations** (not used here): tools like **Alembic** change existing tables safely (add a column) without
losing data. `create_all` only creates missing tables.

Where: `app/database.py`, `/reports/usage` in `app/main.py`

Try it (with Docker running):
```bash
docker compose exec postgres psql -U qa_user -d qa_db -c "SELECT username, cached, prompt_tokens, latency_ms FROM chat_logs;"
```

---

## Part 5: Authentication with passwords, hashing and JWT

**Authentication** = *who are you?* **Authorization** = *what are you allowed to do?*

**Hashing**: a one-way function. `hash("alice123")` → `$2b$12$Kx...`. You can't get the password back from the
hash. At login we hash what the user typed and compare. If the database leaks, attackers get hashes, not passwords.

**bcrypt**: a hashing algorithm made deliberately slow, and it adds a random **salt** (so two users with the
same password get different hashes). Never use plain SHA-256 for passwords: it's too fast to brute-force.

**Token**: after login, instead of sending the password every time, the client sends a token.

**JWT (JSON Web Token)**: a token made of three parts separated by dots: `header.payload.signature`

```
header:    {"alg": "HS256", "typ": "JWT"}
payload:   {"sub": "alice", "role": "user", "exp": 1790000000}    ← claims
signature: HMAC-SHA256(header + payload, JWT_SECRET)
```

- The payload is only **base64-encoded, not encrypted**: anyone can read it (try pasting a token on jwt.io).
  So never put secrets in it.
- The **signature** proves the server made it and nobody changed it. If someone edits `"role": "admin"`,
  the signature no longer matches and we reject it.
- **Claims**: `sub` (subject = user), `exp` (expiry time), custom ones like `role`.
- **HS256**: signing with one shared secret. **RS256**: private key signs, public key verifies (used by SSO).
- **Stateless**: the server doesn't store sessions; any instance can verify any token with the secret.
  This is why JWT is good for multiple instances.
- **Bearer token**: sent in the header `Authorization: Bearer <token>` ("whoever bears this token").

Flow in our code (`app/auth.py`):
1. `/auth/login` → `verify_password()` → `create_token()`
2. `/chat` → `get_current_user()` reads the header → `decode_token()` checks signature and expiry → 401 if bad

---

## Part 6: Authorization with RBAC

**RBAC (Role-Based Access Control)**: permissions belong to **roles**; users have a role.

```python
ROLE_PERMISSIONS = {
    "admin": ["chat", "view_metrics", "view_reports", "manage_users"],
    "user": ["chat"],
    "readonly": ["view_reports"],
}
```

`require_permission("chat")` returns a dependency that gets the user from the token and returns **403** if
their role lacks that permission. Endpoints ask for a permission, not a role, so adding a role is a one-line change.

**SSO (Single Sign-On)**: log in once with your company account (Google, Microsoft) and use many apps.
**OAuth2**: a standard for an app to get an **access token** from an authorisation server.
**OIDC (OpenID Connect)**: adds identity on top of OAuth2 (an **ID token** saying who the user is).
**Identity Provider (IdP)**: the service that logs users in: Okta, Azure AD / Entra ID, Google, Keycloak, Auth0.
**API Gateway**: a front door that checks tokens and rate limits before requests reach services.
**JWKS**: the URL where an IdP publishes its public keys so we can verify its tokens.

In production our `/auth/login` would be replaced by the IdP; the rest (verify JWT, check roles) stays.
Full explanation: ARCHITECTURE.md section 4.

---

## Part 7: Calling the LLM

**LLM (Large Language Model)**: an AI model that generates text (Gemini, GPT, Claude, Llama).
We call it through the provider's **API** using their **SDK** (Software Development Kit = their Python library,
here `google-genai`).

**API key**: a secret string that identifies our account to Google. Comes from env var `GEMINI_API_KEY`.

**Tokens**: LLMs read and write in tokens (pieces of words; ~4 characters or ~¾ of a word in English).
- **prompt tokens / input tokens**: the question
- **completion / output / answer tokens**: the answer
- Providers **charge per token** and limit tokens per minute, so we record them.

**Model**: `gemini-2.5-flash` (main, good + fast), `gemini-2.5-flash-lite` (fallback, cheaper and lighter).

**Mock**: a fake version of something for testing. `LLM_PROVIDER=mock` returns
`"(mock answer) You asked: ..."` so the app works without a key.

### Timeout, retry, backoff, fallback (the important part)

- **Timeout**: stop waiting after N seconds. Without it, a stuck call blocks forever.
- **Retry**: try again; many failures are temporary (network blip, server overloaded).
- **Exponential backoff**: wait 1s, then 2s, then 4s between retries, so we don't hammer a struggling service.
- **Jitter**: add a small random amount to each wait so many clients don't retry at the same instant (production idea).
- **Fallback**: if the main option keeps failing, use a backup (another model).
- **Graceful degradation**: when part of the system fails, keep giving a reduced service instead of crashing.
- **Circuit breaker** (production idea): after many failures, stop calling the service for a while and fail
  fast, like a fuse in your house.

```python
for model in [LLM_MODEL, LLM_FALLBACK_MODEL]:
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            return call_model(model, question)
        except Exception:
            if attempt < LLM_MAX_RETRIES:
                time.sleep(2 ** (attempt - 1))
raise LLMError("All LLM models failed")   # main.py turns this into HTTP 503
```

**Rate limits of LLM providers**: **RPM** (requests per minute), **TPM** (tokens per minute), and
**concurrency** (calls at the same time). Going over gives **429**.

Where: `app/llm.py`

---

## Part 8: Redis (cache and rate limiting)

**Redis**: an in-memory **key-value store** (like a giant Python dict that lives in its own server and is
shared by all app instances). Extremely fast (~1 ms) because data is in RAM.

Commands we use:

| Command | Meaning |
|---|---|
| `SET key value EX 3600` | save value; delete it automatically after 3600 s |
| `GET key` | read value (None if missing/expired) |
| `INCR key` | add 1 to a number (creates it as 1 if missing). **Atomic**: safe when many requests do it at once |
| `EXPIRE key 60` | delete key after 60 s |
| `PING` | are you alive? |

**TTL (Time To Live)**: how long a key lives before Redis deletes it.

### Cache
**Cache**: a fast store of results so you don't recompute them. Our key is
`"answer:" + sha256(question.lower().strip())`. **Cache hit** = found, **cache miss** = not found.
Hit → no LLM call, no tokens, ~1 ms. **Hash** here just turns any-length text into a fixed-length key.

### Rate limiting
**Rate limiting**: limiting how many requests a user can make in a time window. Protects our money (tokens)
and the LLM provider limit, and stops abuse.

**Fixed window counter** (what we use): key `rate:alice:<current minute number>`, `INCR` it, if > 10 → 429.
The key expires after 60 s. Simple; weakness: someone can send 10 at 12:00:59 and 10 at 12:01:00.
Better algorithms: **sliding window**, **token bucket**.

**Why Redis and not a Python dict?** With 3 app instances, a dict would exist 3 times, so each user would get
3× the limit and the cache would be split. Redis is **shared**, so it's **distributed** rate limiting.

**Fail open**: if Redis is down we *allow* requests (instead of blocking everyone). That's a choice:
availability over strictness.

Where: `app/cache.py`

Try it:
```bash
docker compose exec redis redis-cli KEYS '*'
docker compose exec redis redis-cli TTL "answer:<the key>"
```

---

## Part 9: Monitoring with Prometheus metrics

**Monitoring**: watching the system's health with numbers. **Observability** = metrics + logs + traces.

- **Metrics**: numbers over time (requests/sec, latency, errors). Cheap to store, good for graphs and alerts.
- **Logs**: text lines about single events (`LLM call failed (model=..., attempt=1)`).
- **Traces**: the path and timing of one request through every service (OpenTelemetry).

**Prometheus**: a monitoring system that **scrapes** (pulls) `GET /metrics` from every app instance every
few seconds and stores the numbers. **Grafana** draws dashboards from Prometheus. **Alertmanager** sends alerts.

Metric types (`app/metrics.py`):
- **Counter**: only goes up. `http_requests_total`, `llm_tokens_total`, `llm_errors_total`, `cache_hits_total`
- **Histogram**: counts values in **buckets** (≤0.1s, ≤0.5s, ≤1s...) so you can calculate **percentiles**.
- **Labels**: extra dimensions, e.g. `http_requests_total{path="/chat", status="429"}`

**Latency**: how long a request takes. **p95 latency**: 95% of requests are faster than this. We look at p95/p99,
not the average, because the average hides the slow requests that annoy users.

**Health check**: an endpoint (`/health`) the load balancer / Docker / Kubernetes calls to ask "are you OK?".
Ours checks the DB (required → 503 if down) and Redis (optional → reported only).

Try it: log in as admin, then `curl localhost:8000/metrics -H "Authorization: Bearer <token>"`

---

## Part 10: Docker

**Problem Docker solves**: "it works on my machine". Different Python versions, missing libraries, different OS.

**Container**: a lightweight, isolated box with your app + Python + libraries. Runs the same everywhere.
Lighter than a **virtual machine** because it shares the host's OS kernel.

**Image**: the read-only template a container is created from (like a class; a container is the object).
**Dockerfile**: the recipe to build an image. **Registry**: where images are stored (Docker Hub, AWS ECR).

Our `Dockerfile`, line by line:

| Line | Meaning |
|---|---|
| `FROM python:3.11-slim` | Start from an official small Python image |
| `ENV PYTHONUNBUFFERED=1` | Print logs immediately |
| `WORKDIR /code` | `cd /code` inside the image |
| `COPY requirements.txt .` then `RUN pip install ...` | Install libraries. Done before copying code so this **layer is cached**: changing code doesn't reinstall everything |
| `COPY app ./app` | Add our code |
| `RUN useradd ...` / `USER appuser` | Don't run as root (security) |
| `EXPOSE 8000` | Documents the port |
| `CMD ["uvicorn", ...]` | Command run when the container starts |

**Layer**: each Dockerfile instruction makes a layer; unchanged layers are reused (fast rebuilds).
**`.dockerignore`**: files not sent to the build (`.env`, tests, `.git`), like `.gitignore`.
**Volume**: storage that lives outside the container, so Postgres data survives restarts.
**Port mapping** `"8000:80"`: your computer's port 8000 → the container's port 80.

### Docker Compose
**Docker Compose**: run several containers together from one file, `docker-compose.yml`.
Our services: `api`, `nginx`, `postgres`, `redis`.

- Containers find each other **by service name**: the API connects to `postgres:5432` and `redis:6379`
  (Compose provides a private network with DNS).
- `depends_on` + `condition: service_healthy`: start the API only after Postgres and Redis pass their health checks.
- `env_file: .env`: pass our settings into the container.
- `restart: unless-stopped`: restart the container if it crashes.
- `docker compose up --build --scale api=3`: build and start, with 3 API containers.

Useful commands:
```bash
docker compose up --build -d     # start in background
docker compose ps                # what's running + health
docker compose logs -f api       # follow API logs
docker compose down              # stop (add -v to also delete the database volume)
```

---

## Part 11: Load balancing with nginx

**Load balancer**: sits in front of many app instances and spreads requests across them.
**nginx**: a fast web server often used as a **reverse proxy** (receives requests and forwards them to
servers behind it) and load balancer.

```nginx
upstream fastapi_instances {
    server api:8000 max_fails=3 fail_timeout=10s;
}
```

Docker's DNS returns all `api` containers for the name `api`, so nginx spreads requests over them
(**round robin** = take turns). `max_fails` takes a failing instance out for 10 s;
`proxy_next_upstream` retries the request on another instance if one errors.

You can see it working: `docker compose logs api` shows requests landing on `api-1`, `api-2`, `api-3`.

**Horizontal scaling**: more machines/containers (scale out). **Vertical scaling**: bigger machine (scale up).
Horizontal is preferred: no upper limit and no single point of failure. It needs the app to be **stateless**
(no per-user data kept in the app's memory), which ours is: data is in Postgres/Redis, identity is in the JWT.

---

## Part 12: Testing with pytest

**pytest**: Python's most popular test framework. A test is a function starting with `test_` using `assert`.

**TestClient**: sends fake HTTP requests to the FastAPI app in memory, no server needed.

**Fixture**: reusable setup given to tests by name (`client`, `user_headers`, `fake_redis` in `tests/conftest.py`).
`autouse=True` means every test gets it automatically.

**Mocking / monkeypatching**: replacing a real thing with a fake during a test.
- SQLite instead of Postgres, **fakeredis** instead of Redis, mock LLM instead of Gemini → tests need nothing installed.
- `monkeypatch.setattr(llm, "call_model", always_fail)` → simulate Gemini being down and check we return 503.
- We replace `time.sleep` so retry tests don't really wait.

Our 17 tests check: login OK / wrong password, missing / invalid token (401), readonly can't chat (403),
admin-only metrics, chat works, cache hit on the second ask, 422 on empty question, 429 after 5 requests,
retry succeeds after one failure, fallback model is used, 503 when everything fails, chat is logged in the DB.

**Unit test** vs **integration test**: unit tests one function alone; integration tests parts working together.
Ours are mostly integration tests of the API with fakes for external services.

Run: `pytest -v`

---

## Part 13: Scaling words you'll hear (Kubernetes and friends)

You don't need to run these for this project, but you must explain them.

- **Kubernetes (K8s)**: runs containers across many machines; restarts failed ones; scales them.
- **Pod**: the smallest unit in K8s, one (or a few) containers. **Node**: a machine in the cluster.
- **Deployment**: "keep N copies of this pod running"; does **rolling updates** (replace pods a few at a time).
- **Service**: a stable address that load-balances across pods. **Ingress**: HTTP entry from outside.
- **HPA (Horizontal Pod Autoscaler)**: adds/removes pods automatically based on CPU or other metrics.
- **readinessProbe**: "can this pod take traffic?" **livenessProbe**: "is it stuck? restart it".
- **ConfigMap / Secret**: settings and secrets given to pods as env vars.
- **ECS / Fargate**: AWS's simpler alternative to Kubernetes. **EKS**: AWS's managed Kubernetes.
- **Queue** (SQS, RabbitMQ, Redis + Celery/RQ): a list of jobs; **producers** add jobs, **workers** process them.
  Used for long tasks and to absorb spikes. **Asynchronous processing**: reply "202 Accepted, job id 42", do it later.
- **LLM Gateway**: one service all LLM calls go through: holds keys, limits, retries, fallbacks, cost tracking (e.g. LiteLLM).
- **Little's Law**: requests in flight = arrival rate × time per request. 100 RPS × 2 s = 200 concurrent.
- **RPS**: requests per second. **Throughput**: how much work per second. **Latency**: time per request.
- **Single point of failure (SPOF)**: one part whose failure breaks everything (the single EC2 server).
- **High availability**: no SPOF; multiple copies across **availability zones** (separate data centres).
- **Blue-green / canary deployment**: run old and new side by side; move traffic gradually; roll back fast.
- **Idempotent**: doing it twice has the same effect as once (important for retries and queues).
- **RAG (Retrieval-Augmented Generation)** (optional in the brief): find relevant documents in a
  **vector database** using **embeddings** (numbers that represent meaning) and give them to the LLM with the question.

---

## Part 14: How I built it (the order I'd tell an interviewer)

1. **FastAPI basics**: hello world, then `/health`. Learned decorators, Pydantic, `/docs`.
2. **Config**: moved every setting to env vars and `.env` so no secret is in Git.
3. **Database**: SQLAlchemy models for `users` and `chat_logs`; my SQL knowledge mapped directly.
4. **Login + JWT**: bcrypt hashing, creating/verifying tokens, the `Depends` pattern, then RBAC with a permission dict.
5. **LLM**: first a plain Gemini call, then a mock so I could work without a key, then timeout → retry → fallback.
6. **Redis**: cache first (easy win), then rate limiting with `INCR`, then made both survive Redis being down.
7. **Metrics**: Prometheus counters and histograms + a middleware for latency of every request.
8. **Tests**: pytest with SQLite, fakeredis and mocks, including failure cases.
9. **Docker**: Dockerfile, then Compose with Postgres and Redis, then nginx to run several API copies.
   Starting 3 copies at once showed a real bug: all of them tried to create the tables and the demo users at
   the same moment and some crashed. I fixed it by retrying the setup a few times.
   I also hit a library change: SQLAlchemy 2.1 expects the newer `psycopg` driver for `postgresql://`, so I
   wrote `postgresql+psycopg2://` explicitly.
10. **Docs**: architecture, scaling, migration.

---

## Part 15: Run everything yourself (checklist)

```bash
# 1. Tests (no Docker needed)
pip install -r requirements-dev.txt
pytest -v

# 2. Full system
cp .env.example .env              # set JWT_SECRET; optionally LLM_PROVIDER=gemini + GEMINI_API_KEY
docker compose up --build --scale api=3

# 3. In another terminal
curl localhost:8000/health
TOKEN=$(curl -s -X POST localhost:8000/auth/login -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"alice123"}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
curl -X POST localhost:8000/chat -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"What is Redis?"}'
# run the same command again -> "cached": true

# 4. See the data
docker compose exec postgres psql -U qa_user -d qa_db -c "SELECT * FROM chat_logs;"
docker compose exec redis redis-cli KEYS '*'
docker compose logs api | grep "POST /chat"     # requests spread over api-1, api-2, api-3

# 5. Break things on purpose
docker compose stop redis         # chat still works, /health says redis down
docker compose start redis
```

On Windows PowerShell, use the `/docs` page in the browser instead of the `TOKEN=$(...)` line.
