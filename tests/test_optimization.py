import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_temp.db")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth import require_api_key
from app import db_models

client = TestClient(app)


# ---------------------------------------------------------------------------
# 1. GET /search returns X-Response-Time-Ms header
# ---------------------------------------------------------------------------

def test_search_returns_response_time_header(bypass_auth):
    with patch("app.main.search_failures", return_value=[]), \
         patch("app.main.check_rate_limit", return_value=(True, 25)), \
         patch("app.main.get_cached", return_value=None), \
         patch("app.main.set_cached"):
        response = client.get("/search?q=timeout", headers={"Authorization": "Bearer testkey"})
    assert response.status_code == 200
    assert "X-Response-Time-Ms" in response.headers
    assert float(response.headers["X-Response-Time-Ms"]) >= 0


# ---------------------------------------------------------------------------
# 2. GET /search returns X-RateLimit-Remaining header on successful response
# ---------------------------------------------------------------------------

def test_search_returns_rate_limit_remaining_header(bypass_auth):
    with patch("app.main.search_failures", return_value=[]), \
         patch("app.main.check_rate_limit", return_value=(True, 25)), \
         patch("app.main.get_cached", return_value=None), \
         patch("app.main.set_cached"):
        response = client.get("/search?q=timeout", headers={"Authorization": "Bearer testkey"})
    assert response.status_code == 200
    assert "X-RateLimit-Remaining" in response.headers
    assert response.headers["X-RateLimit-Remaining"] == "25"


# ---------------------------------------------------------------------------
# 3. GET /search returns HTTP 429 when rate limit is exceeded
# ---------------------------------------------------------------------------

def test_search_returns_429_when_rate_limited(bypass_auth):
    with patch("app.main.check_rate_limit", return_value=(False, 0)):
        response = client.get("/search?q=timeout", headers={"Authorization": "Bearer testkey"})
    assert response.status_code == 429
    assert "Rate limit exceeded" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 4. GET /search returns cached result on second call; search_failures called once
# ---------------------------------------------------------------------------

def test_search_returns_cached_result_on_second_call(bypass_auth):
    cached_result = {"query": "timeout", "results": []}
    with patch("app.main.check_rate_limit", return_value=(True, 25)), \
         patch("app.main.get_cached", side_effect=[None, cached_result]) as mock_get, \
         patch("app.main.set_cached"), \
         patch("app.main.search_failures", return_value=[]) as mock_search:
        response1 = client.get("/search?q=timeout&n=5", headers={"Authorization": "Bearer testkey"})
        response2 = client.get("/search?q=timeout&n=5", headers={"Authorization": "Bearer testkey"})
    assert response1.status_code == 200
    assert response2.status_code == 200
    assert mock_search.call_count == 1
    assert response2.json() == cached_result


# ---------------------------------------------------------------------------
# 5. POST /analyze returns HTTP 429 when rate limit is exceeded
# ---------------------------------------------------------------------------

def test_analyze_returns_429_when_rate_limited(bypass_auth):
    with patch("app.main.check_rate_limit", return_value=(False, 0)):
        response = client.post(
            "/analyze",
            json={"query": "what failed?"},
            headers={"Authorization": "Bearer testkey"},
        )
    assert response.status_code == 429
    assert "Rate limit exceeded" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 6. check_rate_limit returns (True, 29) on first call, (True, 28) on second
# ---------------------------------------------------------------------------

def test_check_rate_limit_increments():
    from app.rate_limiter import check_rate_limit

    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    mock_redis.incr.return_value = 1

    with patch("app.rate_limiter._redis_client", mock_redis):
        allowed1, remaining1 = check_rate_limit("test-key")

    assert allowed1 is True
    assert remaining1 == 29
    mock_redis.expire.assert_called_once()

    mock_redis.get.return_value = b"1"
    mock_redis.incr.return_value = 2
    mock_redis.expire.reset_mock()

    with patch("app.rate_limiter._redis_client", mock_redis):
        allowed2, remaining2 = check_rate_limit("test-key")

    assert allowed2 is True
    assert remaining2 == 28
    mock_redis.expire.assert_not_called()


# ---------------------------------------------------------------------------
# 7. check_rate_limit returns (True, -1) when Redis is unavailable
# ---------------------------------------------------------------------------

def test_check_rate_limit_fails_open_when_redis_unavailable():
    from app.rate_limiter import check_rate_limit

    mock_redis = MagicMock()
    mock_redis.get.side_effect = Exception("Redis connection error")

    with patch("app.rate_limiter._redis_client", mock_redis):
        allowed, remaining = check_rate_limit("test-key")

    assert allowed is True
    assert remaining == -1


# ---------------------------------------------------------------------------
# 8. get_cached returns None when Redis is unavailable
# ---------------------------------------------------------------------------

def test_get_cached_returns_none_when_redis_unavailable():
    from app.cache import get_cached

    mock_redis = MagicMock()
    mock_redis.get.side_effect = Exception("Redis connection error")

    with patch("app.cache._redis_client", mock_redis):
        result = get_cached("some-key")

    assert result is None
