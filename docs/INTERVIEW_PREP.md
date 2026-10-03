# Interview Prep

## 30-second pitch

> "I built an AI question-answering API with FastAPI. Users log in and get a JWT; the role in the token decides
> what they can do. When someone asks a question, the API checks a per-user rate limit in Redis, looks for a
> cached answer in Redis, and otherwise calls Google Gemini with a timeout, retries with exponential backoff,
> and a fallback model. Every request's latency and token usage goes to Prometheus metrics and a PostgreSQL
> table. It runs with Docker Compose: nginx load-balances across several stateless FastAPI containers, with
> Postgres and Redis. There are 17 pytest tests including failure cases, and I documented how it would scale
> to 500 requests per second on Kubernetes."

## 2-minute walkthrough (follow the request)

1. **Login**: `POST /auth/login` → bcrypt checks the password hash in Postgres → JWT with username, role, expiry.
2. **Chat**: `POST /chat` with `Bearer` token → FastAPI dependency verifies the JWT and checks the role has
   the `chat` permission.
3. **Rate limit**: Redis `INCR` on `rate:<user>:<minute>` → 429 if over 10.
4. **Cache**: Redis key = SHA-256 of the normalised question → if found, return instantly, zero tokens.
5. **LLM**: Gemini call with 20s timeout; on error retry with 1s, 2s backoff; then fallback model; then 503.
6. **Record**: latency + tokens to Prometheus and a `chat_logs` row; return answer, model, cached, tokens, latency.
7. **Deploy**: Docker image, Compose with nginx + N API containers + Postgres + Redis; health checks.

## Why these choices (be ready to defend)

| Choice | One-line reason |
|---|---|
| FastAPI | Validation and docs for free, async support, very common for ML/LLM services |
| Gemini | Free key; the LLM is isolated in `llm.py` so changing provider is one file |
| JWT | Stateless, so any instance can verify it; works with load balancing |
| Redis | Shared across instances; in memory, so fast; TTL and atomic INCR built in |
| PostgreSQL | Structured data (users, logs) with SQL reporting |
| nginx | Shows load balancing across instances locally; in cloud an ALB/Ingress replaces it |
| Mock LLM | Tests and demos without a key or cost; deterministic tests |
| Sync endpoints | Simpler to write and reason about as a first version; async is the planned next step |

---

## Likely questions with answers

### FastAPI / Python

**Q: Why FastAPI over Flask or Django?**
FastAPI validates request bodies with Pydantic, generates OpenAPI docs automatically, supports async, and is
fast. Django is heavy for a small API; Flask needs extra libraries for validation and docs.

**Q: What is `Depends`?**
Dependency injection: FastAPI runs the given function before the endpoint and passes in the result. I use it to
open/close a DB session per request and to check the token and role. If a dependency raises an HTTPException,
the endpoint doesn't run.

**Q: Your endpoints are `def`, not `async def`. Is that a problem?**
FastAPI runs `def` endpoints in a thread pool, so they don't block each other, but each waiting request uses a
thread (about 40 per worker by default). For high concurrency I'd switch to `async def` with the async Gemini
client and an async DB driver, so one process can wait on hundreds of LLM calls. I started sync because the
code is simpler and fine for this load.

**Q: What does Pydantic do here?**
Validates the JSON body: `question` must be a string of 1–2000 characters, otherwise FastAPI returns 422
automatically. It also defines the response shape.

**Q: What's the middleware for?**
It times every request and records it in a Prometheus histogram and a counter labelled by path and status.

### Authentication / Security

**Q: How does JWT work?**
Header + payload + signature. The payload has `sub`, `role`, `exp`. The server signs it with a secret
(HS256). On each request it recomputes the signature: if it matches and `exp` is in the future, the token is valid.
The payload is readable by anyone (base64), so it holds no secrets; the signature makes it tamper-proof.

**Q: What if someone changes their role to admin in the token?**
The signature won't match, so `jwt.decode` raises an error and we return 401.

**Q: How do you log a user out / revoke a JWT?**
With pure JWT you can't before expiry, which is the trade-off of statelessness. Options: short expiry (15 min)
plus refresh tokens; a Redis **blocklist** of revoked token ids checked on each request; or delegate to SSO.

**Q: 401 vs 403?**
401: not authenticated (missing, invalid or expired token, wrong password). 403: authenticated but the role
isn't allowed.

**Q: Why bcrypt and not SHA-256?**
SHA-256 is fast, so attackers can try billions of guesses per second. bcrypt is slow on purpose and salted, so
cracking leaked hashes is much harder.

**Q: How would you move to SSO?**
Users log in with the company Identity Provider (Okta, Azure AD) through OAuth2/OIDC. The IdP issues an
RS256-signed JWT. An API gateway (or our app) verifies it with the IdP's public keys (JWKS) and checks
`iss`, `aud`, `exp`. Roles come from IdP groups in a claim. Our `/auth/login` and password table go away;
`require_permission` stays the same.

**Q: Explain RBAC in your project.**
A dict maps roles to permissions: admin (chat, metrics, reports, manage users), user (chat), readonly (reports).
Endpoints require a permission, not a role. In production the mapping would be in DB tables or come from the IdP.

**Q: How do you keep secrets out of the code?**
Everything comes from environment variables via `config.py`; `.env` is gitignored and `.env.example` has dummy
values. The app refuses to start without `JWT_SECRET`. In production: AWS Secrets Manager / Kubernetes Secrets.

**Q: What about prompt injection?**
Not handled deeply here. In production: a system prompt with clear rules, input length limits (I have 2000
chars), output filtering, never giving the LLM secrets or tools it doesn't need, and logging for abuse review.

### LLM

**Q: How do you handle LLM timeouts and errors?**
The Gemini client has a 20s timeout. Any failure is retried with exponential backoff (1s, 2s...). After
`LLM_MAX_RETRIES` tries the fallback model is used with the same logic. If all fail, `LLMError` → 503 with a
clear message and `llm_errors_total` goes up.

**Q: Why exponential backoff? What's jitter?**
If the provider is overloaded, instant retries make it worse; waiting longer each time gives it room to recover.
Jitter adds randomness so many clients don't retry at the same moment (the "thundering herd").

**Q: Should you retry every error?**
No, and that's a known limitation in my version. A 400 (bad request) or invalid API key will fail every time,
so retrying wastes time. I'd retry only timeouts, 429 and 5xx, and respect `Retry-After`.

**Q: What's the worst-case response time?**
Two models × (20s + 1s wait + 20s) ≈ 80s. Too long for chat, so in production I'd use a lower timeout and a
total time budget per request.

**Q: How do you record token usage?**
Gemini returns `usage_metadata` with `prompt_token_count` and `candidates_token_count`. I add them to a
Prometheus counter and store them in `chat_logs`, so I can compute cost per user with SQL.

**Q: What are RPM / TPM limits and how do you handle them?**
Requests and tokens per minute allowed by the provider. Handling: per-user rate limiting, caching, a global
token counter in Redis to stay under the limit, queueing bursts, multiple keys/providers behind an LLM gateway,
and limiting output tokens.

**Q: How would you add RAG?**
Split documents into chunks, create embeddings, store in a vector DB (pgvector, Qdrant). On a question, embed
it, find the most similar chunks, and send them with the question to the LLM. pgvector would let me keep using Postgres.

### Redis

**Q: What do you use Redis for?**
Caching answers (key = hash of the normalised question, 1-hour TTL) and per-user rate limiting (INCR on a
per-minute key). Both need to be shared across instances, which is why it's Redis and not Python memory.

**Q: How does your rate limiter work and what's wrong with it?**
Fixed window: key `rate:<user>:<minute>`, INCR, expire after 60s, reject over the limit. Weakness: a user can
send 2× the limit across a window boundary, and INCR and EXPIRE are two commands (if the app dies between them
the key has no expiry). Fix: sliding window or token bucket in a Lua script so it's atomic.

**Q: What happens if Redis goes down?**
The app keeps working without cache and rate limit (I catch `RedisError` and fail open), and `/health` reports
`redis: down`. I tested this by stopping the Redis container. Trade-off: during the outage there's no rate limiting.

**Q: Cache invalidation: what if an answer is outdated?**
The TTL (1 hour) bounds staleness. For questions about changing data I'd use a shorter TTL or skip caching.

### Database

**Q: Why PostgreSQL? What do you store?**
Users (hashed passwords, roles) and chat logs (question, answer, model, cached, tokens, latency, time).
Relational data with reporting by SQL, e.g. `/reports/usage` is a GROUP BY.

**Q: Why an ORM if you know SQL?**
Same code on Postgres and SQLite for tests, protection from SQL injection through parameterised queries, and
less boilerplate. For complex reports I can still write raw SQL.

**Q: How do you handle schema changes?**
Currently `create_all` creates missing tables at startup. In production I'd use Alembic migrations, run once in
the deploy pipeline, not by every instance.

**Q: Will the database be a bottleneck at 500 RPS?**
500 small inserts/s is fine for Postgres. Use connection pooling (PgBouncer) so many pods don't open too many
connections, move logging to a queue/background task if needed, and use read replicas for reports.

### Docker / Deployment

**Q: Image vs container?**
An image is the built template (read-only); a container is a running instance of it.

**Q: Why copy requirements.txt before the code in the Dockerfile?**
Layer caching: the dependency install layer is reused unless requirements change, so code changes rebuild fast.

**Q: How do the containers find each other?**
Compose creates a network with DNS; services are reachable by name (`postgres:5432`, `redis:6379`, `api:8000`).

**Q: How does load balancing work in your setup?**
nginx proxies to `api:8000`; with `--scale api=3` Docker DNS returns three containers and nginx spreads requests
across them. Failed instances are skipped (`max_fails`), and failed requests retried on another (`proxy_next_upstream`).
I confirmed it in the logs: requests land on api-1, api-2 and api-3.

**Q: Any problem you hit while building?**
Two. When three API containers started together, they all tried to create tables and insert demo users at the
same time and some crashed on a unique-key error; I added a retry around startup. In production the fix is to
run migrations once as a separate step. Second, SQLAlchemy 2.1 defaults to the newer `psycopg` driver, so I had
to write `postgresql+psycopg2://` in the URL.

**Q: Why run as a non-root user in the container?**
If someone exploits the app, they get a limited user, not root inside the container.

### Scaling & architecture

**Q: How would you handle 100 RPS with spikes to 500?**
Little's Law: with ~2s LLM latency, 100 RPS = 200 requests in flight, 500 RPS = 1,000. Stateless pods behind a
load balancer, HPA on Kubernetes (min sized for 100 RPS, scales to 500), async endpoints, Redis cache to cut LLM
calls, per-user and global rate limits, a queue for long jobs and to absorb spikes, and multiple LLM providers
because 500 RPS × 500 tokens ≈ 15M tokens/min, above normal provider limits. The LLM limit is the real bottleneck.

**Q: Why is HPA on CPU not ideal here?**
The pods mostly wait for the LLM, so CPU stays low even when they're full. Better to scale on in-flight requests,
RPS, or queue length via custom metrics (KEDA / Prometheus adapter).

**Q: When would you use a queue?**
Long or batch tasks (big documents, RAG indexing), and to smooth spikes: accept the job (202), process at the
rate the LLM allows, client polls or gets a webhook. Not for short chats where users expect an instant reply.

**Q: What is a circuit breaker?**
After many failures to a service, stop calling it for a short time and fail fast or use a fallback, then test it
again. Prevents every request from waiting on a dead provider.

**Q: Single EC2 server to 10,000 users: summary?**
Remove the single point of failure: containerise, move DB to RDS Multi-AZ and cache to ElastiCache, run
stateless pods on ECS/EKS across zones behind an ALB, add an LLM gateway with limits and fallbacks, add
monitoring and alerts, move secrets to Secrets Manager. Migrate gradually with weighted traffic (5% → 100%)
and keep the old server for rollback. Details in MIGRATION.md.

**Q: How would you monitor this in production?**
Prometheus scraping `/metrics`, Grafana dashboards (RPS, error rate, p95 latency, LLM latency, tokens/min,
cache hit rate), alerts on error rate and latency and token limits, central JSON logs with request ids,
OpenTelemetry tracing.

### Testing

**Q: How do you test without Gemini, Postgres or Redis?**
Env vars set before import: SQLite DB, `LLM_PROVIDER=mock`; fakeredis replaces the Redis client; `monkeypatch`
replaces `call_model` to simulate timeouts and outages, and `time.sleep` so retries don't wait.

**Q: What tests do you have?**
17: login success/failure, missing/invalid token, role restrictions, chat success, cache hit, validation (422),
rate limit (429), retry then success, fallback model, all-fail 503, and that chats are logged in the DB.

**Q: What would you test next?**
Token expiry, Redis-down behaviour in a unit test, and load tests with Locust or k6. A GitHub Actions workflow
already runs the tests and builds the Docker image on every push.

---

## Honest "what I'd improve" list (interviewers like this)

1. `async` endpoints + async LLM client.
2. Retry only retryable errors; add jitter, a total time budget and a circuit breaker.
3. Alembic migrations instead of `create_all`.
4. Sliding-window / token-bucket rate limiting in a Lua script; a global LLM token limiter.
5. Refresh tokens or SSO; user-management endpoints for admins.
6. Background queue for long tasks; streaming responses.
7. Kubernetes manifests + HPA, automatic deployment (CD), Grafana dashboards.
8. Structured JSON logging with request ids.

## Tips

- Say "I learned X to do Y" for each tool: it shows how you pick things up.
- When you don't know, say what you'd check and where (docs, metrics, logs). Don't guess.
- Draw the diagram from memory: Users → nginx → FastAPI ×N → Redis / Postgres / Gemini (main + fallback).
- Know the numbers: 20s timeout, 2 tries per model, 1-hour cache, 10 requests/min, 17 tests, 3 roles.
