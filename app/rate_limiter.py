import logging
import os

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

RATE_LIMIT = 30
RATE_WINDOW_SECONDS = 60

_redis_client = redis.from_url(REDIS_URL)


def check_rate_limit(api_key_name: str) -> tuple[bool, int]:
    key = f"ratelimit:{api_key_name}"
    try:
        current = _redis_client.get(key)
        current_count = int(current) if current is not None else 0
        if current_count >= RATE_LIMIT:
            return (False, 0)
        new_count = _redis_client.incr(key)
        if new_count == 1:
            _redis_client.expire(key, RATE_WINDOW_SECONDS)
        return (True, RATE_LIMIT - new_count)
    except Exception as exc:
        logger.warning("rate_limit_redis_error", extra={"api_key_name": api_key_name, "error": str(exc)})
        return (True, -1)
