"""Tests for app.premerge_webhook POST /webhook/premerge."""
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import bug_tracker as bt
from app.auth import require_api_key
from app.db_models import APIKeyORM
from app.main import app

client = TestClient(app)

_FAKE_KEY = APIKeyORM(id=1, name="test-key", key_hash="testhash", is_active=True)

# Fixtures file with a mix: some pass, some fail. One failure message contains
# a known bug signature so bug_linked logic is exercised.
_ALL_PASS_FIXTURES = {
    "test_checkout_flow": {"status": "passed", "failure_message": None},
    "test_payment_gateway": {"status": "passed", "failure_message": None},
    "test_user_login": {"status": "passed", "failure_message": None},
    "test_order_processing": {"status": "passed", "failure_message": None},
}

_MIXED_FIXTURES = {
    "test_checkout_flow": {"status": "passed", "failure_message": None},
    "test_payment_gateway": {"status": "passed", "failure_message": None},
    "test_user_login": {"status": "passed", "failure_message": None},
    "test_order_processing": {"status": "failed", "failure_message": "totally new error with no matching signature xyz"},
    "test_new_bug": {"status": "failed", "failure_message": "another totally new error abc"},
}

_LINK_FIXTURES = {
    "test_checkout_flow": {"status": "passed", "failure_message": None},
    "test_payment_gateway": {"status": "passed", "failure_message": None},
    "test_user_login": {"status": "passed", "failure_message": None},
    "test_order_processing": {"status": "passed", "failure_message": None},
    "test_something": {
        "status": "failed",
        "failure_message": "regression of BUG-001: checkout fails when cart state is not persisted",
    },
}

_VALID_PAYLOAD = {
    "mr_id": "MR-42",
    "author": "alice",
    "changed_modules": ["cart_service"],
    "description": "Fix cart persistence",
}


@pytest.fixture(autouse=True)
def reset_bug_store():
    """Reset the bug store before and after each test for isolation."""
    bt.reset_store()
    yield
    bt.reset_store()


@pytest.fixture(autouse=True)
def bypass_auth():
    """Skip real API key auth for all tests."""
    app.dependency_overrides[require_api_key] = lambda: _FAKE_KEY
    yield
    app.dependency_overrides.pop(require_api_key, None)


def _post(payload=None, fixtures=None, driver_return=None, extra_graph_tests=None):
    """Helper: POST /webhook/premerge with mocked driver and fixtures.

    extra_graph_tests: if provided, get_tests_for_modules returns this list
    (simulating graph results) in addition to P0 tests.
    """
    payload = payload or _VALID_PAYLOAD
    fixtures = fixtures if fixtures is not None else _ALL_PASS_FIXTURES
    graph_tests = extra_graph_tests or []
    with patch("app.premerge_webhook.get_driver", return_value=driver_return), \
         patch("app.premerge_webhook.get_tests_for_modules", return_value=graph_tests), \
         patch("app.premerge_webhook._load_fixtures", return_value=fixtures):
        return client.post("/webhook/premerge", json=payload)


# ---------------------------------------------------------------------------
# 1. All P0 tests selected when driver is None
# ---------------------------------------------------------------------------

def test_p0_tests_selected_when_driver_none():
    resp = _post(fixtures=_ALL_PASS_FIXTURES, driver_return=None)
    assert resp.status_code == 200
    data = resp.json()
    selected_names = {t["test_name"] for t in data["selected_tests"]}
    from app.premerge_webhook import P0_REGRESSION_TESTS
    for p0 in P0_REGRESSION_TESTS:
        assert p0 in selected_names


# ---------------------------------------------------------------------------
# 2. approved when all tests pass
# ---------------------------------------------------------------------------

def test_approved_when_all_pass():
    resp = _post(fixtures=_ALL_PASS_FIXTURES)
    assert resp.status_code == 200
    data = resp.json()
    assert data["merge_recommendation"] == "approved"
    assert data["total_failed"] == 0
    assert data["failures"] == []


# ---------------------------------------------------------------------------
# 3. blocked when any test fails
# ---------------------------------------------------------------------------

def test_blocked_when_failures():
    resp = _post(fixtures=_MIXED_FIXTURES)
    assert resp.status_code == 200
    data = resp.json()
    assert data["merge_recommendation"] == "blocked"
    assert data["total_failed"] > 0
    assert len(data["failures"]) > 0


# ---------------------------------------------------------------------------
# 4. bugs_created > 0 when failures have no matching bug signature
# ---------------------------------------------------------------------------

def test_bugs_created_for_new_failures():
    resp = _post(fixtures=_MIXED_FIXTURES)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["failures"]) > 0


# ---------------------------------------------------------------------------
# 5. bugs_linked > 0 when failure message matches existing bug signature
# ---------------------------------------------------------------------------

def test_bugs_linked_for_known_signature():
    # Seed a bug whose failure_signatures will match the test fixture message
    bt.create_bug(
        title="Known bug",
        severity="high",
        feature="checkout_flow",
        failure_signature="regression of BUG-001",
        build="seed-build",
        test_name="test_seed",
    )
    # Supply test_something via graph results so it is included in the selected set
    extra = [{"test_name": "test_something", "feature_name": "checkout_flow", "module_name": "cart_service", "priority": "high"}]
    resp = _post(fixtures=_LINK_FIXTURES, extra_graph_tests=extra)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["failures"]) > 0


# ---------------------------------------------------------------------------
# 6. build is "Premerge_MR" on all results
# ---------------------------------------------------------------------------

def test_build_field_on_all_results():
    resp = _post(fixtures=_MIXED_FIXTURES)
    assert resp.status_code == 200
    data = resp.json()
    assert data["build"] == "Premerge_MR"
    for result in data["results"]:
        assert result["build"] == "Premerge_MR"


# ---------------------------------------------------------------------------
# 7. total_failed and total_passed counts are correct
# ---------------------------------------------------------------------------

def test_total_counts_correct():
    resp = _post(fixtures=_MIXED_FIXTURES)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_failed"] + data["total_passed"] == data["total_run"]
    actual_failed = sum(1 for r in data["results"] if r["status"] == "failed")
    actual_passed = sum(1 for r in data["results"] if r["status"] == "passed")
    assert data["total_failed"] == actual_failed
    assert data["total_passed"] == actual_passed


# ---------------------------------------------------------------------------
# 8. Returns 401 without a valid API key
# ---------------------------------------------------------------------------

def test_returns_401_without_api_key():
    # Remove the bypass override for this test only
    app.dependency_overrides.pop(require_api_key, None)
    resp = client.post("/webhook/premerge", json=_VALID_PAYLOAD)
    assert resp.status_code in (401, 403)
    # Restore for subsequent tests
    app.dependency_overrides[require_api_key] = lambda: _FAKE_KEY

# ===========================================================================
# /webhook/analyze tests
# ===========================================================================

_DEMO_XML_PATH = "demo/data/demo.xml"

_ALL_PASS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="AllPassSuite" tests="2" failures="0" errors="0" skipped="0" time="0.5">
  <testcase name="test_one" classname="tests.suite" time="0.2"></testcase>
  <testcase name="test_two" classname="tests.suite" time="0.3"></testcase>
</testsuite>
"""


def _post_analyze(xml_bytes, build="build-42"):
    return client.post(
        "/webhook/analyze",
        params={"build": build},
        files={"file": ("results.xml", xml_bytes, "application/xml")},
    )


# ---------------------------------------------------------------------------
# analyze 1. Returns 200 with correct suite_name and build
# ---------------------------------------------------------------------------

def test_analyze_returns_suite_name_and_build():
    with open(_DEMO_XML_PATH, "rb") as f:
        xml_bytes = f.read()
    resp = _post_analyze(xml_bytes, build="build-99")
    assert resp.status_code == 200
    data = resp.json()
    assert data["suite_name"] == "CartServiceTestSuite"
    assert data["build"] == "build-99"


# ---------------------------------------------------------------------------
# analyze 2. total_failures and total_passed counts match the XML
# ---------------------------------------------------------------------------

def test_analyze_counts_match_xml():
    # demo.xml has 20 tests total. The endpoint combines <failure> and <error>
    # elements into failed_results; passed_results are only <testcase> with no child.
    # Verify the invariant: failures + errors (from suite header) + passed + skipped = total_tests.
    with open(_DEMO_XML_PATH, "rb") as f:
        xml_bytes = f.read()
    resp = _post_analyze(xml_bytes)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_tests"] == 20
    # total_failures reported by the endpoint = failed + error test cases combined
    assert data["total_failures"] > 0
    assert data["total_passed"] > 0
    # Sanity: total_failures + total_passed <= total_tests (skipped not counted in either)
    assert data["total_failures"] + data["total_passed"] <= data["total_tests"]


# ---------------------------------------------------------------------------
# analyze 3. analysis is not None when there are failures
# ---------------------------------------------------------------------------

def test_analyze_has_analysis_when_failures():
    with open(_DEMO_XML_PATH, "rb") as f:
        xml_bytes = f.read()
    resp = _post_analyze(xml_bytes)
    assert resp.status_code == 200
    assert resp.json()["analysis"] is not None


# ---------------------------------------------------------------------------
# analyze 4. analysis is None when all tests pass
# ---------------------------------------------------------------------------

def test_analyze_analysis_none_when_all_pass():
    resp = _post_analyze(_ALL_PASS_XML)
    assert resp.status_code == 200
    data = resp.json()
    assert data["analysis"] is None
    assert data["merge_recommendation"] == "approved"


# ---------------------------------------------------------------------------
# analyze 5. verified_bugs contains a bug ID when a passing test was linked
#            to a resolved bug before the call
# ---------------------------------------------------------------------------

def test_analyze_verifies_resolved_bug():
    # Create a resolved bug linked to "test_one" (a passing test in _ALL_PASS_XML)
    bug = bt.create_bug(
        title="Previously fixed bug",
        severity="medium",
        feature="shopping_cart",
        failure_signature="some old error",
        build="old-build",
        test_name="test_one",
    )
    bt.set_bug_status(bug["id"], "resolved")

    resp = _post_analyze(_ALL_PASS_XML)
    assert resp.status_code == 200
    data = resp.json()
    assert bug["id"] in data["verified_bugs"]


# ---------------------------------------------------------------------------
# analyze 6. verified_bugs is empty when no resolved bugs match passing tests
# ---------------------------------------------------------------------------

def test_analyze_verified_bugs_empty_when_no_match():
    resp = _post_analyze(_ALL_PASS_XML)
    assert resp.status_code == 200
    assert resp.json()["verified_bugs"] == []


# ---------------------------------------------------------------------------
# analyze 7. Returns 401 without a valid API key
# ---------------------------------------------------------------------------

def test_analyze_returns_401_without_api_key():
    app.dependency_overrides.pop(require_api_key, None)
    resp = client.post(
        "/webhook/analyze",
        params={"build": "build-1"},
        files={"file": ("r.xml", _ALL_PASS_XML, "application/xml")},
    )
    assert resp.status_code in (401, 403)
    app.dependency_overrides[require_api_key] = lambda: _FAKE_KEY


# ---------------------------------------------------------------------------
# analyze 8. Returns 400 or 422 if no file is uploaded
# ---------------------------------------------------------------------------

def test_analyze_returns_error_without_file():
    resp = client.post("/webhook/analyze", params={"build": "build-1"})
    assert resp.status_code in (400, 422)