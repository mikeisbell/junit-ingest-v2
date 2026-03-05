"""Tests for Bearer token authentication."""
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database, db_models
from app.auth import generate_key, hash_key
from app.main import app

SAMPLE_XML = Path(__file__).parent / "sample.xml"

client = TestClient(app)

_ADMIN_TOKEN = "test-admin-token-secret"


@pytest.fixture
def valid_api_key(reset_store):
    """Insert a hashed API key into the test DB and return the plaintext."""
    plaintext = generate_key()
    record = db_models.APIKeyORM(name="test-key", key_hash=hash_key(plaintext))
    db = database.SessionLocal()
    try:
        db.add(record)
        db.commit()
    finally:
        db.close()
    return plaintext


# ---------------------------------------------------------------------------
# POST /results auth tests
# ---------------------------------------------------------------------------


def test_post_results_no_auth_returns_403(reset_store):
    with open(SAMPLE_XML, "rb") as f:
        response = client.post("/results", files={"file": ("sample.xml", f, "text/xml")})
    assert response.status_code in (401, 403)


def test_post_results_invalid_token_returns_401(reset_store, chroma_store):
    with open(SAMPLE_XML, "rb") as f:
        response = client.post(
            "/results",
            files={"file": ("sample.xml", f, "text/xml")},
            headers={"Authorization": "Bearer invalid-token"},
        )
    assert response.status_code == 401


def test_post_results_valid_token_succeeds(valid_api_key, chroma_store):
    with open(SAMPLE_XML, "rb") as f:
        response = client.post(
            "/results",
            files={"file": ("sample.xml", f, "text/xml")},
            headers={"Authorization": f"Bearer {valid_api_key}"},
        )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /search auth tests
# ---------------------------------------------------------------------------


def test_get_search_no_auth_returns_403(chroma_store):
    response = client.get("/search", params={"q": "error"})
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /health is public
# ---------------------------------------------------------------------------


def test_get_health_no_auth_returns_200(reset_store):
    mock_client = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
    mock_client.heartbeat.return_value = {}
    with patch("app.main._get_client", return_value=mock_client):
        response = client.get("/health")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /keys tests
# ---------------------------------------------------------------------------


def test_post_keys_no_admin_header_returns_422(reset_store):
    response = client.post("/keys", json={"name": "dev"})
    assert response.status_code == 422


def test_post_keys_invalid_admin_token_returns_401(reset_store):
    with patch.dict(os.environ, {"ADMIN_TOKEN": _ADMIN_TOKEN}):
        response = client.post(
            "/keys",
            json={"name": "dev"},
            headers={"X-Admin-Token": "wrong-token"},
        )
    assert response.status_code == 401


def test_post_keys_valid_admin_token_returns_201_with_key(reset_store):
    with patch.dict(os.environ, {"ADMIN_TOKEN": _ADMIN_TOKEN}):
        response = client.post(
            "/keys",
            json={"name": "dev"},
            headers={"X-Admin-Token": _ADMIN_TOKEN},
        )
    assert response.status_code == 201
    body = response.json()
    assert "key" in body
    assert body["name"] == "dev"


def test_key_from_post_keys_can_authenticate(reset_store, chroma_store):
    with patch.dict(os.environ, {"ADMIN_TOKEN": _ADMIN_TOKEN}):
        create_resp = client.post(
            "/keys",
            json={"name": "ci"},
            headers={"X-Admin-Token": _ADMIN_TOKEN},
        )
    assert create_resp.status_code == 201
    plaintext = create_resp.json()["key"]

    with open(SAMPLE_XML, "rb") as f:
        ingest_resp = client.post(
            "/results",
            files={"file": ("sample.xml", f, "text/xml")},
            headers={"Authorization": f"Bearer {plaintext}"},
        )
    assert ingest_resp.status_code == 200
