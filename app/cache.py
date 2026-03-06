import hashlib
import json
import logging
import os

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

_redis_client = redis.from_url(REDIS_URL)


def get_cached(key: str) -> dict | None:
    try:
        value = _redis_client.get(key)
        if value is None:
            return None
        return json.loads(value)
    except Exception as exc:
        logger.warning("cache_get_error", extra={"key": key, "error": str(exc)})
        return None


def set_cached(key: str, value: dict, ttl_seconds: int = 600) -> None:
    try:
        _redis_client.setex(key, ttl_seconds, json.dumps(value))
    except Exception as exc:
        logger.warning("cache_set_error", extra={"key": key, "error": str(exc)})


def make_search_cache_key(query: str, n_results: int) -> str:
    digest = hashlib.md5(f"{query}:{n_results}".encode()).hexdigest()
    return f"search:{digest}"


def make_analyze_cache_key(query: str, n_results: int) -> str:
    digest = hashlib.md5(f"{query}:{n_results}".encode()).hexdigest()
    return f"analyze:{digest}"
