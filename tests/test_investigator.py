import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_temp.db")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth import require_api_key
from app import db_models

client = TestClient(app)


@pytest.fixture
def bypass_auth_investigator():
    fake_key = db_models.APIKeyORM(id=999, name="bypass-test-key", key_hash="bypass", is_active=True)
    app.dependency_overrides[require_api_key] = lambda: fake_key
    yield
    app.dependency_overrides.pop(require_api_key, None)


# ---------------------------------------------------------------------------
# 1. POST /investigate/{suite_id} returns 202
# ---------------------------------------------------------------------------

def test_post_investigate_returns_202(bypass_auth_investigator):
    mock_task = MagicMock()
    mock_task.id = "invest-task-id-456"
    with patch("app.main.investigate_suite_task.delay", return_value=mock_task) as mock_delay:
        response = client.post(
            "/investigate/1",
            headers={"Authorization": "Bearer testkey"},
        )
    assert response.status_code == 202
    data = response.json()
    assert data["task_id"] == "invest-task-id-456"
    assert data["status"] == "pending"
    assert data["suite_id"] == 1
    mock_delay.assert_called_once_with(suite_id=1)


# ---------------------------------------------------------------------------
# 2. GET /investigate/result/{task_id} when pending returns 200 + "pending"
# ---------------------------------------------------------------------------

def test_get_investigate_result_pending(bypass_auth_investigator):
    mock_result = MagicMock()
    mock_result.state = "PENDING"
    with patch("app.main.celery_app.AsyncResult", return_value=mock_result):
        response = client.get(
            "/investigate/result/some-task-id",
            headers={"Authorization": "Bearer testkey"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "some-task-id"
    assert data["status"] == "pending"


# ---------------------------------------------------------------------------
# 3. GET /investigate/result/{task_id} when complete returns full result
# ---------------------------------------------------------------------------

def test_get_investigate_result_complete(bypass_auth_investigator):
    mock_result = MagicMock()
    mock_result.state = "SUCCESS"
    mock_result.result = {
        "suite_id": 1,
        "suite_name": "SampleTestSuite",
        "total_tests": 5,
        "total_failures": 1,
        "total_errors": 1,
        "similar_failures_found": 3,
        "report": {
            "summary": "One test failed due to an assertion error.",
            "root_cause_hypotheses": [
                {"hypothesis": "Logic error in multiplication", "confidence": "high"}
            ],
            "recurring_patterns": [
                {"test_name": "test_multiplication_fails", "failure_count": 3}
            ],
            "recommended_next_steps": ["Review the multiplication logic in the codebase."],
        },
        "steps_executed": ["fetch_suite", "search_similar", "get_stats", "generate_report"],
    }
    with patch("app.main.celery_app.AsyncResult", return_value=mock_result):
        response = client.get(
            "/investigate/result/some-task-id",
            headers={"Authorization": "Bearer testkey"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "some-task-id"
    assert data["status"] == "complete"
    assert "suite_id" in data
    assert "suite_name" in data
    assert "report" in data
    assert "steps_executed" in data


# ---------------------------------------------------------------------------
# 4. GET /investigate/result/{task_id} when failed returns 200 + "failed"
# ---------------------------------------------------------------------------

def test_get_investigate_result_failed(bypass_auth_investigator):
    mock_result = MagicMock()
    mock_result.state = "FAILURE"
    mock_result.result = Exception("investigation blew up")
    with patch("app.main.celery_app.AsyncResult", return_value=mock_result):
        response = client.get(
            "/investigate/result/some-task-id",
            headers={"Authorization": "Bearer testkey"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "some-task-id"
    assert data["status"] == "failed"
    assert "error" in data


# ---------------------------------------------------------------------------
# 5. investigate_suite executes all four steps
# ---------------------------------------------------------------------------

def test_investigate_suite_all_steps():
    from app.investigator import investigate_suite

    mock_db = MagicMock()
    suite_data = {
        "id": 1,
        "name": "SampleTestSuite",
        "total_tests": 5,
        "total_failures": 1,
        "total_errors": 1,
        "total_skipped": 1,
        "elapsed_time": 1.234,
        "test_cases": [
            {"name": "test_foo", "status": "failed", "failure_message": "AssertionError: expected 4 got 5"},
        ],
    }
    stats_data = {"stats": [{"name": "test_foo", "failure_count": 3}]}
    search_data = {"results": [{"test_case_id": 99, "suite_id": 2, "name": "test_foo", "failure_message": "AssertionError", "distance": 0.1}]}
    report_json = '{"summary": "One test failed.", "root_cause_hypotheses": [], "recurring_patterns": [], "recommended_next_steps": []}'

    mock_response = MagicMock()
    mock_block = MagicMock()
    mock_block.text = report_json
    mock_response.content = [mock_block]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("app.investigator.execute_get_suite_by_id", return_value=suite_data) as mock_suite, \
         patch("app.investigator.execute_search_failures", return_value=search_data) as mock_search, \
         patch("app.investigator.execute_get_failure_stats", return_value=stats_data) as mock_stats, \
         patch("app.investigator.anthropic.Anthropic", return_value=mock_client):
        result = investigate_suite(suite_id=1, db=mock_db)

    assert "suite_id" in result
    assert "report" in result
    assert "steps_executed" in result
    assert result["steps_executed"] == ["fetch_suite", "search_similar", "get_stats", "generate_report"]
    mock_suite.assert_called_once()
    mock_search.assert_called_once()
    mock_stats.assert_called_once()
    mock_client.messages.create.assert_called_once()


# ---------------------------------------------------------------------------
# 6. investigate_suite returns early when suite not found
# ---------------------------------------------------------------------------

def test_investigate_suite_not_found():
    from app.investigator import investigate_suite

    mock_db = MagicMock()

    with patch("app.investigator.execute_get_suite_by_id", return_value={"error": "Suite 999 not found."}) as mock_suite, \
         patch("app.investigator.execute_search_failures") as mock_search, \
         patch("app.investigator.execute_get_failure_stats") as mock_stats, \
         patch("app.investigator.anthropic.Anthropic") as mock_anthropic:
        result = investigate_suite(suite_id=999, db=mock_db)

    assert "error" in result
    assert result["suite_id"] == 999
    mock_search.assert_not_called()
    mock_stats.assert_not_called()
    mock_anthropic.assert_not_called()
