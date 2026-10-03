# Redis is used for two things:
#   1. Cache  - if the same question was asked before, return the saved answer (no LLM call, no cost)
#   2. Rate limit - each user can make only RATE_LIMIT_PER_MINUTE chat requests per minute
#
# If Redis is down, the app still works (just without cache / rate limit).
# This is called "graceful degradation".

import hashlib
import json
import logging
import time

import redis

from app import config

logger = logging.getLogger(__name__)

redis_client = redis.Redis.from_url(config.REDIS_URL, decode_responses=True, socket_timeout=2)


def make_cache_key(question):
    # Same question (ignoring case and spaces at the ends) -> same key
    text = question.strip().lower()
    return "answer:" + hashlib.sha256(text.encode()).hexdigest()


def get_cached_answer(question):
    try:
        value = redis_client.get(make_cache_key(question))
        return json.loads(value) if value else None
    except redis.RedisError as error:
        logger.warning("Redis read failed: %s", error)
        return None


def save_answer(question, result):
    try:
        redis_client.set(make_cache_key(question), json.dumps(result), ex=config.CACHE_TTL_SECONDS)
    except redis.RedisError as error:
        logger.warning("Redis write failed: %s", error)


def is_rate_limited(username):
    # Fixed window counter: one key per user per minute, e.g. "rate:alice:28761234"
    # INCR adds 1; the key deletes itself after 60 seconds.
    window = int(time.time() // 60)
    key = f"rate:{username}:{window}"
    try:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, 60)
        return count > config.RATE_LIMIT_PER_MINUTE
    except redis.RedisError as error:
        logger.warning("Redis rate limit check failed: %s", error)
        return False  # fail open: allow the request if Redis is down


def redis_is_up():
    try:
        return redis_client.ping()
    except redis.RedisError:
        return False
