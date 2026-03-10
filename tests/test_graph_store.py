import os
from unittest.mock import MagicMock, patch

# Must be set before any app imports so database.py picks up SQLite
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_temp.db")

import pytest
from fastapi.testclient import TestClient

from app import db_models
from app.auth import require_api_key
from app.graph import get_driver, get_gap_analysis, get_tests_for_modules, ingest_suite_to_graph
from app.main import app
from app.models import TestCase, TestSuiteResult

client = TestClient(app)


@pytest.fixture
def bypass_auth_graph():
    """Override require_api_key with a no-op to skip auth for graph endpoint tests."""
    fake_key = db_models.APIKeyORM(id=999, name="bypass-test-key", key_hash="bypass", is_active=True)
    app.dependency_overrides[require_api_key] = lambda: fake_key
    yield
    app.dependency_overrides.pop(require_api_key, None)


# ---------------------------------------------------------------------------
# 1. get_driver returns None when connection fails
# ---------------------------------------------------------------------------

def test_get_driver_returns_none_on_failure():
    """get_driver() must return None without raising when Neo4j is unreachable."""
    with patch("app.graph.driver.GraphDatabase.driver", side_effect=Exception("Connection refused")):
        result = get_driver()
    assert result is None


# ---------------------------------------------------------------------------
# 2. ingest_suite_to_graph skips silently when driver is None
# ---------------------------------------------------------------------------

def test_ingest_suite_skips_when_driver_none():
    """ingest_suite_to_graph with driver=None must not raise."""
    suite = TestSuiteResult(
        name="TestSuite",
        total_tests=1,
        total_failures=0,
        total_errors=0,
        total_skipped=0,
        elapsed_time=0.1,
        test_cases=[TestCase(name="test_foo", status="passed")],
    )
    # Should complete without raising even though driver is None (fail-open behavior).
    ingest_suite_to_graph(None, suite, {})


# ---------------------------------------------------------------------------
# 3. get_tests_for_modules returns empty list when driver is None
# ---------------------------------------------------------------------------

def test_get_tests_for_modules_returns_empty_when_driver_none():
    """get_tests_for_modules with driver=None returns an empty list (fail-open)."""
    result = get_tests_for_modules(None, ["payment_processor"])
    assert result == []


# ---------------------------------------------------------------------------
# 4. get_gap_analysis returns error dict when driver is None
# ---------------------------------------------------------------------------

def test_get_gap_analysis_returns_error_when_driver_none():
    """get_gap_analysis with driver=None returns the 'graph unavailable' error."""
    result = get_gap_analysis(None, "BUG-001")
    assert result == {"error": "graph unavailable"}


# ---------------------------------------------------------------------------
# 5. POST /graph/churn returns 503 when graph is unavailable
# ---------------------------------------------------------------------------

def test_churn_endpoint_returns_503_when_graph_unavailable(bypass_auth_graph):
    """POST /graph/churn returns 503 when app.state.neo4j_driver is None."""
    app.state.neo4j_driver = None
    with patch("app.graph.get_tests_for_modules", return_value=[]):
        response = client.post("/graph/churn", json={"modules": ["payment_processor"]})
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# 6. GET /graph/gaps/{bug_id} returns 404 for unknown bug
# ---------------------------------------------------------------------------

def test_gaps_endpoint_returns_404_for_unknown_bug(bypass_auth_graph):
    """GET /graph/gaps/{bug_id} returns 404 when get_gap_analysis reports bug not found."""
    # Use a non-None mock driver so the endpoint proceeds past the 503 guard.
    app.state.neo4j_driver = MagicMock()
    with patch("app.main.get_gap_analysis", return_value={"error": "bug not found"}):
        response = client.get("/graph/gaps/UNKNOWN-999")
    assert response.status_code == 404
