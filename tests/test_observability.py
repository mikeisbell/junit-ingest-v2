"""Tests for observability: trace IDs and /health endpoint."""
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
# Trace ID header tests
# ---------------------------------------------------------------------------


def test_post_results_returns_trace_id_header(reset_store, chroma_store):
    with open(SAMPLE_XML, "rb") as f:
        response = client.post("/results", files={"file": ("sample.xml", f, "text/xml")})
    assert response.status_code == 200
    assert "x-trace-id" in response.headers


def test_get_search_returns_trace_id_header(chroma_store):
    response = client.get("/search", params={"q": "error"})
    assert response.status_code == 200
    assert "x-trace-id" in response.headers


def test_post_analyze_returns_trace_id_header(chroma_store):
    with patch("app.rag.analyze_failures", return_value="analysis text"):
        response = client.post("/analyze", json={"query": "error"})
    assert response.status_code == 200
    assert "x-trace-id" in response.headers


def test_request_trace_id_echoed_in_response(chroma_store):
    custom_id = "my-custom-trace-id-1234"
    response = client.get("/search", params={"q": "error"}, headers={"X-Trace-ID": custom_id})
    assert response.status_code == 200
    assert response.headers.get("x-trace-id") == custom_id


# ---------------------------------------------------------------------------
# /health endpoint tests
# ---------------------------------------------------------------------------


def test_health_ok_when_all_dependencies_reachable(reset_store):
    mock_client = MagicMock()
    mock_client.heartbeat.return_value = {"nanosecond heartbeat": 1}
    with patch("app.main._get_client", return_value=mock_client):
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["postgres"]["status"] == "ok"
    assert body["dependencies"]["chromadb"]["status"] == "ok"


def test_health_degraded_when_chromadb_unreachable(reset_store):
    mock_client = MagicMock()
    mock_client.heartbeat.side_effect = Exception("Connection refused")
    with patch("app.main._get_client", return_value=mock_client):
        response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["postgres"]["status"] == "ok"
    assert body["dependencies"]["chromadb"]["status"] == "error"
    assert "Connection refused" in body["dependencies"]["chromadb"]["detail"]
