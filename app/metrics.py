# Prometheus metrics. Prometheus is a monitoring tool that reads GET /metrics
# every few seconds and stores the numbers so we can draw graphs (in Grafana) and set alerts.
#
# Counter   = a number that only goes up (total requests, total tokens)
# Histogram = records durations in buckets, so we can get average and p95 latency

from prometheus_client import Counter, Histogram

REQUESTS = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_latency_seconds", "HTTP request latency in seconds", ["path"]
)
LLM_LATENCY = Histogram(
    "llm_latency_seconds", "Time taken by the LLM call in seconds"
)
LLM_TOKENS = Counter(
    "llm_tokens_total", "LLM tokens used", ["type"]  # type = prompt or answer
)
LLM_ERRORS = Counter(
    "llm_errors_total", "Chat requests where every LLM attempt failed"
)
CACHE_HITS = Counter(
    "cache_hits_total", "Chat answers served from Redis cache"
)
