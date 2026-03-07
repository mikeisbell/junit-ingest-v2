import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.ci_webhook
from app.ci_webhook import process_ci_webhook
from app.main import app
from app.models import TestSuiteResult

SAMPLE_XML = Path(__file__).parent / "sample.xml"

client = TestClient(app)


def _make_suite(name: str = "BenchSuite", tests: int = 10, failures: int = 5) -> TestSuiteResult:
    return TestSuiteResult(
        name=name,
        total_tests=tests,
        total_failures=failures,
        total_errors=0,
        total_skipped=0,
        elapsed_time=1.0,
        test_cases=[],
    )


# ---------------------------------------------------------------------------
# 1. Below threshold: no issue created
# ---------------------------------------------------------------------------

def test_below_threshold_no_issue(monkeypatch):
    monkeypatch.setenv("CI_FAILURE_THRESHOLD", "0.5")
    suite = _make_suite(tests=10, failures=2)  # 20% < 50% threshold
    db = MagicMock()

    with patch("app.ci_webhook.investigate_suite") as mock_inv, \
         patch("app.ci_webhook.create_issue") as mock_ci:
        result = process_ci_webhook(suite, db)

    mock_ci.assert_not_called()
    assert result is None


# ---------------------------------------------------------------------------
# 2. Zero failures: no issue created
# ---------------------------------------------------------------------------

def test_zero_failures_no_issue():
    suite = _make_suite(tests=10, failures=0)
    db = MagicMock()

    with patch("app.ci_webhook.create_issue") as mock_ci:
        result = process_ci_webhook(suite, db)

    mock_ci.assert_not_called()
    assert result is None


# ---------------------------------------------------------------------------
# 3. Above threshold: issue created with correct title
# ---------------------------------------------------------------------------

def test_above_threshold_creates_issue(monkeypatch):
    monkeypatch.setenv("CI_FAILURE_THRESHOLD", "0.2")
    suite = _make_suite(tests=10, failures=3)  # 30% >= 20% threshold
    db = MagicMock()

    mock_report = {
        "report": {
            "summary": "Tests failed due to connection issues.",
            "root_cause_hypotheses": [{"hypothesis": "DB timeout", "confidence": "high"}],
            "recommended_next_steps": ["Check DB connection", "Run tests again"],
        }
    }

    with patch("app.ci_webhook.investigate_suite", return_value=mock_report), \
         patch("app.ci_webhook.create_issue", return_value={"mock": True, "status": "logged"}) as mock_ci:
        result = process_ci_webhook(suite, db)

    mock_ci.assert_called_once()
    call_args = mock_ci.call_args[0][0]
    assert call_args.title.startswith("CI Failure:")


# ---------------------------------------------------------------------------
# 4. High failure rate sets p1 priority
# ---------------------------------------------------------------------------

def test_high_failure_rate_sets_p1_priority(monkeypatch):
    monkeypatch.setenv("CI_FAILURE_THRESHOLD", "0.2")
    suite = _make_suite(tests=10, failures=6)  # 60% >= 50% -> p1
    db = MagicMock()

    mock_report = {
        "report": {
            "summary": "Many tests failed.",
            "root_cause_hypotheses": [],
            "recommended_next_steps": [],
        }
    }

    with patch("app.ci_webhook.investigate_suite", return_value=mock_report), \
         patch("app.ci_webhook.create_issue", return_value={"mock": True, "status": "logged"}) as mock_ci:
        process_ci_webhook(suite, db)

    call_args = mock_ci.call_args[0][0]
    assert call_args.priority == "p1"


# ---------------------------------------------------------------------------
# 5. Webhook endpoint does not require authentication
# ---------------------------------------------------------------------------

def test_webhook_endpoint_no_auth_required(monkeypatch):
    monkeypatch.setenv("CI_FAILURE_THRESHOLD", "1.0")  # Prevent triggering investigation
    xml_content = SAMPLE_XML.read_bytes()

    response = client.post(
        "/webhook/ci",
        files={"file": ("sample.xml", xml_content, "application/xml")},
    )
    # No Authorization header sent — must not return 401 or 403
    assert response.status_code not in (401, 403)


# ---------------------------------------------------------------------------
# 6. Webhook endpoint returns the correct response shape
# ---------------------------------------------------------------------------

def test_webhook_endpoint_returns_correct_shape():
    xml_content = SAMPLE_XML.read_bytes()

    with patch("app.main.process_ci_webhook", return_value={"mock": True}):
        response = client.post(
            "/webhook/ci",
            files={"file": ("sample.xml", xml_content, "application/xml")},
        )

    assert response.status_code == 200
    data = response.json()
    assert "suite" in data
    assert "tests" in data
    assert "failures" in data
    assert "failure_rate" in data
    assert "issue_created" in data
    assert "devrev_result" in data
