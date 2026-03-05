import os
from unittest.mock import MagicMock, patch

# Must be set before any app imports so database.py picks up SQLite
os.environ["DATABASE_URL"] = "sqlite:///./test_temp.db"

import chromadb
import pytest

from app import database, db_models
from app.auth import require_api_key
from app.main import app


@pytest.fixture
def reset_store():
    """Drop and recreate all tables to provide a clean state for each API test."""
    db_models.Base.metadata.drop_all(bind=database.engine)
    db_models.Base.metadata.create_all(bind=database.engine)
    yield
    db_models.Base.metadata.drop_all(bind=database.engine)


@pytest.fixture
def chroma_store():
    """Provide an isolated in-memory ChromaDB client for each test."""
    ephemeral = chromadb.Client()
    # Drop the collection so each test starts with a clean slate
    try:
        ephemeral.delete_collection("failure_messages")
    except Exception:
        pass
    with patch("app.vector_store._get_client", return_value=ephemeral):
        yield ephemeral


@pytest.fixture
def bypass_auth():
    """Override require_api_key with a no-op to skip auth for non-auth tests."""
    fake_key = db_models.APIKeyORM(id=999, name="bypass-test-key", key_hash="bypass", is_active=True)
    app.dependency_overrides[require_api_key] = lambda: fake_key
    yield
    app.dependency_overrides.pop(require_api_key, None)


@pytest.fixture
def mock_embed_task():
    """Patch embed_failures_task.delay with a no-op MagicMock."""
    mock = MagicMock()
    with patch("app.main.embed_failures_task.delay", mock):
        yield mock
