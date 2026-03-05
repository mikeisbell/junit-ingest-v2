from unittest.mock import patch

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


def test_analyze_returns_200(reset_store, chroma_store):
    """POST /analyze with a valid query returns 200 with expected keys."""
    with patch("app.main.search_failures", return_value=MOCK_FAILURES), \
         patch("app.main.analyze_failures", return_value="Login tests fail due to auth issues."):
        response = client.post("/analyze", json={"query": "why are login tests failing?"})

    assert response.status_code == 200
    body = response.json()
    assert "query" in body
    assert "failures_used" in body
    assert "analysis" in body
    assert body["query"] == "why are login tests failing?"
    assert body["failures_used"] == 1
    assert body["analysis"] == "Login tests fail due to auth issues."


def test_analyze_empty_query_returns_400(chroma_store):
    """POST /analyze with an empty query returns HTTP 400."""
    response = client.post("/analyze", json={"query": ""})
    assert response.status_code == 400
    assert "query is required" in response.json()["detail"]

    response = client.post("/analyze", json={"query": "   "})
    assert response.status_code == 400


def test_analyze_service_error_returns_502(chroma_store):
    """POST /analyze returns HTTP 502 when analyze_failures raises an exception."""
    with patch("app.main.search_failures", return_value=MOCK_FAILURES), \
         patch("app.main.analyze_failures", side_effect=Exception("API unavailable")):
        response = client.post("/analyze", json={"query": "why are tests failing?"})

    assert response.status_code == 502
    assert "unavailable" in response.json()["detail"].lower()


def test_analyze_no_failures_returns_200(chroma_store):
    """POST /analyze when no failures exist returns 200 with failures_used=0."""
    with patch("app.main.search_failures", return_value=[]), \
         patch("app.main.analyze_failures", return_value="No relevant failures found for this query."):
        response = client.post("/analyze", json={"query": "any failures?"})

    assert response.status_code == 200
    body = response.json()
    assert body["failures_used"] == 0
    assert body["analysis"] == "No relevant failures found for this query."
