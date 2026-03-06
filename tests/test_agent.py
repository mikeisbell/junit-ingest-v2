import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_temp.db")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth import require_api_key
from app import database, db_models

client = TestClient(app)


@pytest.fixture
def bypass_auth_agent():
    fake_key = db_models.APIKeyORM(id=999, name="bypass-test-key", key_hash="bypass", is_active=True)
    app.dependency_overrides[require_api_key] = lambda: fake_key
    yield
    app.dependency_overrides.pop(require_api_key, None)


# ---------------------------------------------------------------------------
# 1. POST /agent with valid Bearer token returns 202 with task_id and status
# ---------------------------------------------------------------------------

def test_post_agent_returns_202(bypass_auth_agent):
    mock_task = MagicMock()
    mock_task.id = "test-task-id-123"
    with patch("app.main.run_agent_task.delay", return_value=mock_task) as mock_delay:
        response = client.post(
            "/agent",
            json={"query": "which tests are failing most often?"},
            headers={"Authorization": "Bearer testkey"},
        )
    assert response.status_code == 202
    data = response.json()
    assert data["task_id"] == "test-task-id-123"
    assert data["status"] == "pending"
    mock_delay.assert_called_once_with(query="which tests are failing most often?")


# ---------------------------------------------------------------------------
# 2. POST /agent with empty query returns 400
# ---------------------------------------------------------------------------

def test_post_agent_empty_query_returns_400(bypass_auth_agent):
    response = client.post(
        "/agent",
        json={"query": "   "},
        headers={"Authorization": "Bearer testkey"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "query is required"


def test_post_agent_blank_query_returns_400(bypass_auth_agent):
    response = client.post(
        "/agent",
        json={"query": ""},
        headers={"Authorization": "Bearer testkey"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 3. GET /agent/{task_id} when task is pending returns 200 with status "pending"
# ---------------------------------------------------------------------------

def test_get_agent_pending(bypass_auth_agent):
    mock_result = MagicMock()
    mock_result.state = "PENDING"
    with patch("app.main.celery_app.AsyncResult", return_value=mock_result):
        response = client.get(
            "/agent/some-task-id",
            headers={"Authorization": "Bearer testkey"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "some-task-id"
    assert data["status"] == "pending"


# ---------------------------------------------------------------------------
# 4. GET /agent/{task_id} when task is complete returns 200 with full result
# ---------------------------------------------------------------------------

def test_get_agent_complete(bypass_auth_agent):
    mock_result = MagicMock()
    mock_result.state = "SUCCESS"
    mock_result.result = {
        "query": "which tests are failing most often?",
        "answer": "Based on the data, test_foo fails the most.",
        "tools_called": ["get_failure_stats", "search_failures"],
        "iterations": 2,
    }
    with patch("app.main.celery_app.AsyncResult", return_value=mock_result):
        response = client.get(
            "/agent/some-task-id",
            headers={"Authorization": "Bearer testkey"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "some-task-id"
    assert data["status"] == "complete"
    assert "answer" in data
    assert "tools_called" in data
    assert "iterations" in data


# ---------------------------------------------------------------------------
# 5. GET /agent/{task_id} when task failed returns 200 with status "failed"
# ---------------------------------------------------------------------------

def test_get_agent_failed(bypass_auth_agent):
    mock_result = MagicMock()
    mock_result.state = "FAILURE"
    mock_result.result = Exception("something went wrong")
    with patch("app.main.celery_app.AsyncResult", return_value=mock_result):
        response = client.get(
            "/agent/some-task-id",
            headers={"Authorization": "Bearer testkey"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "some-task-id"
    assert data["status"] == "failed"
    assert "error" in data


# ---------------------------------------------------------------------------
# 6. Test execute_tool dispatch with get_failure_stats
# ---------------------------------------------------------------------------

def test_execute_tool_get_failure_stats():
    from app.agent_tools import execute_tool

    mock_db = MagicMock()
    # Simulate two failed test cases
    tc1 = MagicMock()
    tc1.name = "test_foo"
    tc1.status = "failed"
    tc2 = MagicMock()
    tc2.name = "test_foo"
    tc2.status = "failed"
    tc3 = MagicMock()
    tc3.name = "test_bar"
    tc3.status = "error"

    mock_query = MagicMock()
    mock_query.filter.return_value.all.return_value = [tc1, tc2, tc3]
    mock_db.query.return_value = mock_query

    result = execute_tool("get_failure_stats", {"limit": 10}, mock_db)
    assert "stats" in result
    assert isinstance(result["stats"], list)


# ---------------------------------------------------------------------------
# 7. Test execute_tool with unknown tool name
# ---------------------------------------------------------------------------

def test_execute_tool_unknown():
    from app.agent_tools import execute_tool

    mock_db = MagicMock()
    result = execute_tool("nonexistent_tool", {}, mock_db)
    assert "error" in result
    assert "nonexistent_tool" in result["error"]
