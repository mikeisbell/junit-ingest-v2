"""
Integration tests for the JUnit XML Ingestion Service.
Runs against a live service; not a pytest file.
Uses only the standard library for HTTP calls.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request


SERVICE_URL = os.environ.get("SERVICE_URL", "http://localhost:8001")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

if not ADMIN_TOKEN:
    print("ERROR: ADMIN_TOKEN environment variable is not set.")
    sys.exit(1)


def make_request(method, path, headers=None, body=None):
    """Make an HTTP request and return (status_code, parsed_json_body)."""
    url = SERVICE_URL + path
    if headers is None:
        headers = {}
    data = body if body is None else (body if isinstance(body, bytes) else body)
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {}
    return status, parsed


failures = []
passed = 0
total = 0

api_key = None
task_id = None


def run_test(name, fn):
    global passed, total
    total += 1
    try:
        fn()
        print(f"PASS [{name}]")
        passed += 1
    except AssertionError as exc:
        reason = str(exc) if str(exc) else "assertion failed"
        print(f"FAIL [{name}] — {reason}")
        failures.append((name, reason))
    except Exception as exc:
        reason = str(exc)
        print(f"FAIL [{name}] — {reason}")
        failures.append((name, reason))


# ---------------------------------------------------------------------------
# Test 1: Health check
# ---------------------------------------------------------------------------
def test_health_check():
    status, body = make_request("GET", "/health")
    assert status == 200, f"expected 200, got {status}"
    assert body.get("status") == "ok", f"expected status 'ok', got {body.get('status')!r}"

run_test("Health check", test_health_check)


# ---------------------------------------------------------------------------
# Test 2: Issue API key
# ---------------------------------------------------------------------------
def test_issue_api_key():
    global api_key
    payload = json.dumps({"name": "ci"}).encode()
    status, body = make_request(
        "POST",
        "/keys",
        headers={"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"},
        body=payload,
    )
    assert status == 201, f"expected 201, got {status}"
    assert "key" in body, f"response missing 'key' field: {body}"
    api_key = body["key"]

run_test("Issue API key", test_issue_api_key)


# ---------------------------------------------------------------------------
# Test 3: Reject unauthenticated request
# ---------------------------------------------------------------------------
def test_reject_unauthenticated():
    status, _ = make_request("POST", "/results")
    assert status == 401, f"expected 401, got {status}"

run_test("Reject unauthenticated request", test_reject_unauthenticated)


# ---------------------------------------------------------------------------
# Test 4: Ingest JUnit XML
# ---------------------------------------------------------------------------
JUNIT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="IntegrationTestSuite" tests="2" failures="1" errors="0" skipped="0" time="0.5">
  <testcase name="test_pass" time="0.1"/>
  <testcase name="test_fail" time="0.4">
    <failure message="AssertionError: integration test failure">Expected true but got false</failure>
  </testcase>
</testsuite>
"""

def test_ingest_junit_xml():
    if api_key is None:
        raise AssertionError("api_key not available (Issue API key test failed)")
    boundary = "----CIBoundary1234"
    filename = "results.xml"
    xml_bytes = JUNIT_XML.encode()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/xml\r\n"
        f"\r\n"
    ).encode() + xml_bytes + f"\r\n--{boundary}--\r\n".encode()
    status, response_body = make_request(
        "POST",
        "/results",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        body=body,
    )
    assert status == 200, f"expected 200, got {status}: {response_body}"
    assert response_body.get("name") == "IntegrationTestSuite", (
        f"expected name 'IntegrationTestSuite', got {response_body.get('name')!r}"
    )

run_test("Ingest JUnit XML", test_ingest_junit_xml)


# ---------------------------------------------------------------------------
# Test 5: Semantic search
# ---------------------------------------------------------------------------
def test_semantic_search():
    if api_key is None:
        raise AssertionError("api_key not available (Issue API key test failed)")
    status, body = make_request(
        "GET",
        "/search?q=assertion+error&n=3",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert status == 200, f"expected 200, got {status}"
    assert "results" in body, f"response missing 'results' key: {body}"

run_test("Semantic search", test_semantic_search)


# ---------------------------------------------------------------------------
# Test 6: Submit analyze job
# ---------------------------------------------------------------------------
def test_submit_analyze_job():
    global task_id
    if api_key is None:
        raise AssertionError("api_key not available (Issue API key test failed)")
    payload = json.dumps({"query": "why is the integration test failing?", "n": 3}).encode()
    status, body = make_request(
        "POST",
        "/analyze",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        body=payload,
    )
    assert status == 202, f"expected 202, got {status}: {body}"
    assert "task_id" in body, f"response missing 'task_id': {body}"
    assert body.get("status") == "pending", f"expected status 'pending', got {body.get('status')!r}"
    task_id = body["task_id"]

run_test("Submit analyze job", test_submit_analyze_job)


# ---------------------------------------------------------------------------
# Test 7: Poll for analyze result
# ---------------------------------------------------------------------------
def test_poll_analyze_result():
    if api_key is None:
        raise AssertionError("api_key not available (Issue API key test failed)")
    if task_id is None:
        raise AssertionError("task_id not available (Submit analyze job test failed)")
    deadline = time.time() + 30
    while time.time() < deadline:
        status, body = make_request(
            "GET",
            f"/analyze/{task_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert status == 200, f"expected 200, got {status}"
        job_status = body.get("status")
        if job_status in ("complete", "failed"):
            return
        time.sleep(2)
    raise AssertionError("analyze job did not resolve within 30 seconds")

run_test("Poll for analyze result", test_poll_analyze_result)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print(f"\nIntegration tests complete: {passed}/{total} passed")

if failures:
    sys.exit(1)
