from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _bypass_auth_for_module(bypass_auth):
    """Automatically bypass API key auth for all tests in this module."""


MOCK_FAILURES = [
    {
        "test_case_id": 1,
        "suite_id": 1,
        "name": "test_login",
        "failure_message": "AssertionError: Expected 200 but got 401",
        "distance": 0.12,
    }
]


def test_analyze_returns_200(chroma_store):
    """POST /analyze with a valid query now returns 202 dispatching an async task."""
    mock_task = MagicMock()
    mock_task.id = "celery-task-abc"
    with patch("app.main.analyze_failures_task.delay", return_value=mock_task):
        response = client.post("/analyze", json={"query": "why are login tests failing?"})
    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "celery-task-abc"
    assert body["status"] == "pending"


def test_analyze_empty_query_returns_400(chroma_store):
    """POST /analyze with an empty query returns HTTP 400."""
    response = client.post("/analyze", json={"query": ""})
    assert response.status_code == 400
    assert "query is required" in response.json()["detail"]

    response = client.post("/analyze", json={"query": "   "})
    assert response.status_code == 400


def test_analyze_service_error_returns_502(chroma_store):
    """POST /analyze always returns 202; analysis errors surface in the task result, not HTTP."""
    mock_task = MagicMock()
    mock_task.id = "celery-task-def"
    with patch("app.main.analyze_failures_task.delay", return_value=mock_task):
        response = client.post("/analyze", json={"query": "why are tests failing?"})
    assert response.status_code == 202


def test_analyze_no_failures_returns_200(chroma_store):
    """POST /analyze returns 202 regardless of whether failures exist."""
    mock_task = MagicMock()
    mock_task.id = "celery-task-ghi"
    with patch("app.main.analyze_failures_task.delay", return_value=mock_task):
        response = client.post("/analyze", json={"query": "any failures?"})
    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "celery-task-ghi"
    assert body["status"] == "pending"
