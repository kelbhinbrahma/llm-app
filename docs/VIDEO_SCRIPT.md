# Video Script (under 5 minutes)

**Before recording**

- `docker compose up --build -d --scale api=3` and wait until `docker compose ps` shows all healthy.
- For real answers set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY` in `.env` (mock works too: just say so).
- Open: the README (architecture diagram), VS Code with `app/`, a terminal, and http://localhost:8000/docs
- Log in once as `alice` in `/docs` (Authorize button) so the demo is quick.
- Speak slowly. ~130 words per minute; this script is about 600 words.

---

### 0:00 – 0:30 · Introduction (show README)

> "Hi, I'm Kelbhin, a third-year B.Tech AI and ML student. This is my AI question-answering API. A user logs in,
> asks a question, and gets an answer from Google Gemini. Around that I added the production pieces from the
> brief: JWT authentication with roles, Redis caching and rate limiting, PostgreSQL logging, retries with a
> fallback model, Prometheus metrics, tests, and Docker with a load balancer."

### 0:30 – 1:15 · Architecture (show the diagram)

> "Requests come into nginx, which load-balances across several FastAPI containers. The containers are
> stateless: users and chat logs live in PostgreSQL, the cache and rate-limit counters live in Redis, and the
> user's identity is inside the JWT. So any container can serve any request, and I can scale with one flag.
> The LLM client calls Gemini 2.5 Flash, and if that keeps failing, falls back to Flash Lite.
> Prometheus can scrape the metrics endpoint."

### 1:15 – 2:30 · Code tour (VS Code, ~15 seconds per file)

> "`config.py` reads everything from environment variables, so no secret is in the code; `.env` is gitignored.
> `auth.py`: passwords are hashed with bcrypt, login returns a JWT with the username, role and expiry, and a
> small dictionary maps roles to permissions: admin, user and read-only.
> `llm.py` is the core: each model is tried with a timeout and retried with exponential backoff; then the
> fallback model; if everything fails the API returns 503 instead of hanging.
> `cache.py`: the cache key is a hash of the question; rate limiting uses Redis INCR on a per-user,
> per-minute key, and if Redis is down the app keeps working without them.
> `main.py` ties it together in the `/chat` endpoint: rate limit, cache, LLM, then record latency and tokens."

### 2:30 – 3:45 · Live demo (browser `/docs` + terminal)

1. `GET /health` → *"Database and Redis are up."*
2. `POST /chat` "What is Docker?" → *"Here's the answer, the model used, token counts and latency."*
3. Same question again → *"Now `cached` is true, zero tokens, a few milliseconds."*
4. Log in as `viewer` and try `/chat` → *"403: the read-only role can't use chat, but it can see `/reports/usage`."*
5. Terminal: `docker compose logs api | grep "POST /chat"` → *"Requests are spread over three containers."*
6. Terminal: `docker compose exec postgres psql -U qa_user -d qa_db -c "SELECT username, cached, prompt_tokens, latency_ms FROM chat_logs;"` → *"Every request is logged."*
7. (Optional) `docker compose stop redis`, ask again → *"Still answers; health shows Redis down. That's graceful degradation."*

### 3:45 – 4:15 · Tests

Run `pytest -q` → *"17 tests. They use SQLite, a fake Redis and a mock LLM, so they need no Docker or API key.
They also simulate failures: one test makes the first LLM call time out and checks the retry works, another
makes the main model fail and checks the fallback answers, and another checks we return 503 when everything fails."*

### 4:15 – 4:55 · Scaling and wrap-up (show ARCHITECTURE.md)

> "For 100 requests per second with spikes to 500: with about two seconds per LLM call that's up to a thousand
> requests in flight. I'd run this on Kubernetes with an autoscaler, make the endpoints async, rely on the Redis
> cache and rate limits, and use a queue for long jobs. The real limit is the LLM provider's tokens per minute,
> so I'd add an LLM gateway with multiple providers. The docs also cover moving from a single EC2 server to ten
> thousand users with a gradual, low-downtime migration. Thank you!"

---

**If you go over time**, cut step 7 of the demo and shorten the code tour to `llm.py` and `main.py` only.
