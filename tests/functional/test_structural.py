import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.agent import run_agent
from app.investigator import investigate_suite
from app.main import app
from app.rag import analyze_failures


def test_investigate_report_structure():
    mock_db = MagicMock()
    report_data = {
        "summary": "Two tests failed due to assertion errors.",
        "root_cause_hypotheses": [{"hypothesis": "Incorrect expected values", "confidence": "high"}],
        "recurring_patterns": [{"test_name": "test_foo", "failure_count": 3}],
        "recommended_next_steps": ["Review expected values in test assertions"],
    }
    mock_content = MagicMock()
    mock_content.text = json.dumps(report_data)
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 50

    suite_data = {
        "id": 1,
        "name": "Test Suite",
        "total_tests": 3,
        "total_failures": 2,
        "total_errors": 0,
        "test_cases": [
            {
                "status": "failed",
                "failure_message": "AssertionError: expected 1 but got 2",
                "test_case_id": 1,
            }
        ],
    }

    with (
        patch("app.investigator.execute_get_suite_by_id", return_value=suite_data),
        patch("app.investigator.execute_search_failures", return_value={"results": []}),
        patch("app.investigator.execute_get_failure_stats", return_value={"stats": []}),
        patch("app.investigator.anthropic.Anthropic") as mock_anthropic,
    ):
        mock_anthropic.return_value.messages.create.return_value = mock_response
        result = investigate_suite(suite_id=1, db=mock_db)

    assert "suite_id" in result
    assert "report" in result
    assert "steps_executed" in result
    assert set(result["steps_executed"]) == {"fetch_suite", "search_similar", "get_stats", "generate_report"}
    assert "summary" in result["report"]
    assert "root_cause_hypotheses" in result["report"]
    assert "recurring_patterns" in result["report"]
    assert "recommended_next_steps" in result["report"]


def test_investigate_early_exit_on_missing_suite():
    mock_db = MagicMock()

    with (
        patch("app.investigator.execute_get_suite_by_id", return_value={"error": "Suite 999 not found."}),
        patch("app.investigator.execute_get_failure_stats") as mock_stats,
    ):
        result = investigate_suite(suite_id=999, db=mock_db)

    assert "error" in result
    mock_stats.assert_not_called()


def test_analyze_failures_returns_structure():
    mock_content = MagicMock()
    mock_content.text = "Test analysis response."
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 50

    failures = [
        {
            "test_case_id": 1,
            "suite_id": 1,
            "name": "test_fail",
            "failure_message": "AssertionError",
            "distance": 0.5,
        }
    ]

    with patch("app.rag.anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = mock_response
        result = analyze_failures(query="test query", failures=failures)

    assert isinstance(result, str)
    assert len(result) > 0


def test_analyze_failures_empty_list_skips_api():
    result = analyze_failures(query="test query", failures=[])
    assert result == "No relevant failures found for this query."


def test_agent_returns_structure_with_mocked_api():
    mock_db = MagicMock()
    mock_content = MagicMock()
    mock_content.text = "Mocked agent response."
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_response.stop_reason = "end_turn"
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 50

    with (
        patch("app.agent_tools.execute_search_failures"),
        patch("app.agent_tools.execute_get_suite_by_id"),
        patch("app.agent_tools.execute_get_recent_failures"),
        patch("app.agent_tools.execute_get_failure_stats"),
        patch("app.agent.anthropic.Anthropic") as mock_anthropic,
    ):
        mock_anthropic.return_value.messages.create.return_value = mock_response
        result = run_agent(query="test query", db=mock_db)

    assert "query" in result
    assert "answer" in result
    assert "tools_called" in result
    assert "iterations" in result
    assert result["answer"] == "Mocked agent response."


def test_rate_limit_returns_429(bypass_auth):
    client = TestClient(app)

    with patch("app.main.check_rate_limit", return_value=(False, 0)):
        response = client.get("/search", params={"q": "test query"})

    assert response.status_code == 429
    assert "Rate limit exceeded" in response.text


def test_cache_hit_skips_vector_store(bypass_auth):
    client = TestClient(app)
    cached_result = {
        "query": "test query",
        "results": [
            {
                "test_case_id": 1,
                "name": "test_foo",
                "failure_message": "AssertionError",
                "distance": 0.1,
            }
        ],
    }

    with (
        patch("app.main.get_cached", return_value=cached_result),
        patch("app.main.check_rate_limit", return_value=(True, 25)),
        patch("app.main.search_failures") as mock_search,
    ):
        response = client.get("/search", params={"q": "test query"})

    assert response.status_code == 200
    mock_search.assert_not_called()


def test_cache_miss_calls_vector_store_and_sets_cache(bypass_auth):
    client = TestClient(app)

    with (
        patch("app.main.get_cached", return_value=None),
        patch("app.main.check_rate_limit", return_value=(True, 25)),
        patch("app.main.search_failures", return_value=[]) as mock_search,
        patch("app.main.set_cached") as mock_set,
    ):
        response = client.get("/search", params={"q": "test query"})

    assert response.status_code == 200
    mock_search.assert_called_once()
    mock_set.assert_called_once()
