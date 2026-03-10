from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLE_XML = Path(__file__).parent / "fixtures" / "test.xml"

client = TestClient(app)


@pytest.fixture(autouse=True)
def _bypass_auth_for_module(bypass_auth):
    """Automatically bypass API key auth for all tests in this module."""


def test_search_returns_results_after_ingest(reset_store, chroma_store):
    """Ingesting a file with failures then searching should return matching results."""
    from app.vector_store import embed_failures as _embed

    def sync_embed(suite_id, test_cases):
        _embed(suite_id=suite_id, test_cases=test_cases)

    with patch("app.main.embed_failures_task.delay", side_effect=sync_embed):
        with open(SAMPLE_XML, "rb") as f:
            response = client.post("/results", files={"file": ("test.xml", f, "text/xml")})
    assert response.status_code == 200

    search_response = client.get("/search", params={"q": "AssertionError"})
    assert search_response.status_code == 200

    body = search_response.json()
    assert body["query"] == "AssertionError"
    assert len(body["results"]) >= 1

    first = body["results"][0]
    assert isinstance(first["distance"], float)
    assert isinstance(first["test_case_id"], int)
    assert isinstance(first["suite_id"], int)
    assert isinstance(first["name"], str)
    assert isinstance(first["failure_message"], str)


def test_search_empty_query_returns_400(chroma_store):
    """An empty or whitespace-only query string should return HTTP 400."""
    response = client.get("/search", params={"q": ""})
    assert response.status_code == 400
    assert "q is required" in response.json()["detail"]

    response = client.get("/search", params={"q": "   "})
    assert response.status_code == 400


def test_search_no_failures_returns_empty(reset_store, chroma_store):
    """Searching when no failures have been ingested should return an empty results list."""
    response = client.get("/search", params={"q": "some failure"})
    assert response.status_code == 200

    body = response.json()
    assert body["query"] == "some failure"
    assert body["results"] == []
