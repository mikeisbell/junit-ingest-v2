import time

import pytest
import requests


def _poll_task(service_url, auth_headers, endpoint, task_id, timeout=60):
    """Poll a task endpoint until status is complete or failed, or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = requests.get(
            f"{service_url}/{endpoint}/{task_id}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        if data.get("status") in ("complete", "failed"):
            return data
        time.sleep(3)
    pytest.fail(f"Task {task_id} did not complete within {timeout} seconds")


@pytest.mark.behavioral
def test_semantic_search_assertion_error(service_url, auth_headers, ingested_suite):
    response = requests.get(
        f"{service_url}/search",
        params={"q": "AssertionError expected value did not match", "n": 5},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    results = data.get("results", [])
    assert len(results) > 0
    assert any(
        "assertionerror" in r.get("failure_message", "").lower()
        or "assert" in r.get("failure_message", "").lower()
        for r in results
    )
    assert all(isinstance(r.get("distance"), float) for r in results)


@pytest.mark.behavioral
def test_semantic_search_connection_error(service_url, auth_headers, ingested_suite):
    response = requests.get(
        f"{service_url}/search",
        params={"q": "connection refused timeout failed to connect", "n": 5},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    results = data.get("results", [])
    assert any(
        "connection" in r.get("failure_message", "").lower()
        or "timeout" in r.get("failure_message", "").lower()
        for r in results
    )


@pytest.mark.behavioral
def test_semantic_search_null_pointer(service_url, auth_headers, ingested_suite):
    response = requests.get(
        f"{service_url}/search",
        params={"q": "NullPointerException AttributeError NoneType object", "n": 5},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    results = data.get("results", [])
    assert any(
        "none" in r.get("failure_message", "").lower()
        or "null" in r.get("failure_message", "").lower()
        or "attribute" in r.get("failure_message", "").lower()
        for r in results
    )


@pytest.mark.behavioral
def test_analyze_produces_coherent_response(service_url, auth_headers, ingested_suite, known_failure_xml):
    ingest_response = requests.post(
        f"{service_url}/results",
        files={"file": ("known_failure.xml", known_failure_xml.encode(), "application/xml")},
        headers=auth_headers,
    )
    assert ingest_response.status_code in (200, 201, 202)

    analyze_response = requests.post(
        f"{service_url}/analyze",
        json={"query": "why is the discount calculation failing?", "n": 3},
        headers=auth_headers,
    )
    assert analyze_response.status_code == 202
    task_id = analyze_response.json()["task_id"]

    result = _poll_task(service_url, auth_headers, "analyze", task_id, timeout=60)
    assert result["status"] == "complete"
    assert isinstance(result.get("analysis"), str)
    assert len(result["analysis"]) > 20
    assert isinstance(result.get("failures_used"), int)
    assert result["failures_used"] >= 0


@pytest.mark.behavioral
def test_agent_calls_get_failure_stats(service_url, auth_headers, ingested_suite):
    agent_response = requests.post(
        f"{service_url}/agent",
        json={"query": "which tests have failed most often across all suites?"},
        headers=auth_headers,
    )
    assert agent_response.status_code == 202
    task_id = agent_response.json()["task_id"]

    result = _poll_task(service_url, auth_headers, "agent", task_id, timeout=60)
    assert result["status"] == "complete"
    assert isinstance(result.get("tools_called"), list)
    assert len(result["tools_called"]) > 0
    assert "get_failure_stats" in result["tools_called"]
    assert isinstance(result.get("answer"), str)
    assert len(result["answer"]) > 0


@pytest.mark.behavioral
def test_investigate_structured_report(service_url, auth_headers, ingested_suite):
    investigate_response = requests.post(
        f"{service_url}/investigate/1",
        headers=auth_headers,
    )
    assert investigate_response.status_code == 202
    task_id = investigate_response.json()["task_id"]

    result = _poll_task(service_url, auth_headers, "investigate/result", task_id, timeout=90)
    assert result["status"] == "complete"
    report = result.get("report", {})
    assert "summary" in report
    assert "root_cause_hypotheses" in report
    assert "recommended_next_steps" in report
    assert isinstance(report["summary"], str)
    assert len(report["summary"]) > 0
    assert isinstance(report["recommended_next_steps"], list)
    assert len(report["recommended_next_steps"]) > 0
    assert {"fetch_suite", "search_similar", "get_stats", "generate_report"}.issubset(
        set(result.get("steps_executed", []))
    )
