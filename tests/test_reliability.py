"""Tests for async task dispatch and reliability features."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLE_XML = Path(__file__).parent / "sample.xml"

client = TestClient(app)


@pytest.fixture(autouse=True)
def _bypass_auth_for_module(bypass_auth):
    """Automatically bypass API key auth for all tests in this module."""


# ---------------------------------------------------------------------------
# POST /results dispatches embed task
# ---------------------------------------------------------------------------


def test_post_results_dispatches_embed_task(reset_store, chroma_store):
    """POST /results dispatches the embed task and returns HTTP 200."""
    with patch("app.main.embed_failures_task.delay") as mock_delay:
        with open(SAMPLE_XML, "rb") as f:
            response = client.post(
                "/results",
                files={"file": ("sample.xml", f, "text/xml")},
            )
    assert response.status_code == 200
    mock_delay.assert_called_once()
    call_kwargs = mock_delay.call_args.kwargs
    assert "suite_id" in call_kwargs
    assert "test_cases" in call_kwargs
    assert isinstance(call_kwargs["suite_id"], int)


# ---------------------------------------------------------------------------
# POST /analyze async dispatch
# ---------------------------------------------------------------------------


def test_post_analyze_returns_202_with_task_id(chroma_store):
    """POST /analyze returns 202 and a response body with task_id and status pending."""
    mock_task = MagicMock()
    mock_task.id = "test-task-id-123"
    with patch("app.main.analyze_failures_task.delay", return_value=mock_task):
        response = client.post("/analyze", json={"query": "why are login tests failing?"})
    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "test-task-id-123"
    assert body["status"] == "pending"


# ---------------------------------------------------------------------------
# GET /analyze/{task_id} polling
# ---------------------------------------------------------------------------


def test_get_analyze_task_pending():
    """GET /analyze/{task_id} returns status pending when task is PENDING."""
    mock_result = MagicMock()
    mock_result.state = "PENDING"
    with patch("app.main.celery_app.AsyncResult", return_value=mock_result):
        response = client.get("/analyze/some-task-id")
    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == "some-task-id"
    assert body["status"] == "pending"


def test_get_analyze_task_success():
    """GET /analyze/{task_id} returns status complete with result when task succeeded."""
    mock_result = MagicMock()
    mock_result.state = "SUCCESS"
    mock_result.result = {
        "query": "why are tests failing?",
        "failures_used": 3,
        "analysis": "Based on the retrieved failures...",
    }
    with patch("app.main.celery_app.AsyncResult", return_value=mock_result):
        response = client.get("/analyze/some-task-id")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["query"] == "why are tests failing?"
    assert body["failures_used"] == 3
    assert body["analysis"] == "Based on the retrieved failures..."


def test_get_analyze_task_failed():
    """GET /analyze/{task_id} returns status failed when task failed."""
    mock_result = MagicMock()
    mock_result.state = "FAILURE"
    mock_result.result = Exception("Analysis service error")
    with patch("app.main.celery_app.AsyncResult", return_value=mock_result):
        response = client.get("/analyze/some-task-id")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert "error" in body


# ---------------------------------------------------------------------------
# GET /health includes redis
# ---------------------------------------------------------------------------


def test_health_ok_includes_redis(reset_store):
    """GET /health returns 200 with redis status ok when all dependencies are healthy."""
    mock_chroma = MagicMock()
    mock_chroma.heartbeat.return_value = {}
    mock_redis_conn = MagicMock()
    mock_redis_conn.ping.return_value = True
    with patch("app.main._get_client", return_value=mock_chroma), \
         patch("redis.from_url", return_value=mock_redis_conn):
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["redis"]["status"] == "ok"


def test_health_degraded_when_redis_unreachable(reset_store):
    """GET /health returns 503 with redis status error when Redis is unreachable."""
    mock_chroma = MagicMock()
    mock_chroma.heartbeat.return_value = {}
    with patch("app.main._get_client", return_value=mock_chroma), \
         patch("redis.from_url", side_effect=Exception("Connection refused")):
        response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["redis"]["status"] == "error"
    assert "Connection refused" in body["dependencies"]["redis"]["detail"]
