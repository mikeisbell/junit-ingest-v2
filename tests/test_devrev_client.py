import json
import os
from unittest.mock import MagicMock, patch

import pytest

from app.integrations.devrev import DevRevIssue, create_issue


# ---------------------------------------------------------------------------
# 1. Mock mode returns logged result
# ---------------------------------------------------------------------------

def test_mock_mode_returns_logged_result(monkeypatch):
    monkeypatch.setenv("DEVREV_MOCK", "true")
    issue = DevRevIssue(title="Test Issue", body="Test body")
    result = create_issue(issue)
    assert result["mock"] is True
    assert result["status"] == "logged"
    assert result["title"] == "Test Issue"


# ---------------------------------------------------------------------------
# 2. Mock mode never calls the API
# ---------------------------------------------------------------------------

def test_mock_mode_does_not_call_api(monkeypatch):
    monkeypatch.setenv("DEVREV_MOCK", "true")
    issue = DevRevIssue(title="Test Issue", body="Test body")
    with patch("urllib.request.urlopen") as mock_urlopen:
        create_issue(issue)
    mock_urlopen.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Live mode raises RuntimeError when credentials are missing
# ---------------------------------------------------------------------------

def test_live_mode_missing_credentials_raises(monkeypatch):
    monkeypatch.setenv("DEVREV_MOCK", "false")
    monkeypatch.setenv("DEVREV_PAT", "")
    monkeypatch.setenv("DEVREV_PART_ID", "PROD-1")
    monkeypatch.setenv("DEVREV_OWNER_ID", "owner-123")
    issue = DevRevIssue(title="Test Issue", body="Test body")
    with pytest.raises(RuntimeError):
        create_issue(issue)


# ---------------------------------------------------------------------------
# 4. Live mode succeeds with HTTP 201
# ---------------------------------------------------------------------------

def test_live_mode_success(monkeypatch):
    monkeypatch.setenv("DEVREV_MOCK", "false")
    monkeypatch.setenv("DEVREV_PAT", "test-pat")
    monkeypatch.setenv("DEVREV_PART_ID", "PROD-1")
    monkeypatch.setenv("DEVREV_OWNER_ID", "owner-123")

    mock_response = MagicMock()
    mock_response.status = 201
    mock_response.read.return_value = json.dumps({"work": {"id": "ISS-123"}}).encode()

    issue = DevRevIssue(title="CI Failure", body="Body text")
    with patch("urllib.request.urlopen", return_value=mock_response):
        result = create_issue(issue)

    assert result == {"work": {"id": "ISS-123"}}


# ---------------------------------------------------------------------------
# 5. Live mode raises RuntimeError on API failure (non-201 status)
# ---------------------------------------------------------------------------

def test_live_mode_api_failure_raises(monkeypatch):
    monkeypatch.setenv("DEVREV_MOCK", "false")
    monkeypatch.setenv("DEVREV_PAT", "test-pat")
    monkeypatch.setenv("DEVREV_PART_ID", "PROD-1")
    monkeypatch.setenv("DEVREV_OWNER_ID", "owner-123")

    mock_response = MagicMock()
    mock_response.status = 400
    mock_response.read.return_value = b'{"error": "bad request"}'

    issue = DevRevIssue(title="CI Failure", body="Body text")
    with patch("urllib.request.urlopen", return_value=mock_response):
        with pytest.raises(RuntimeError):
            create_issue(issue)
