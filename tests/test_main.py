from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.parser import JUnitParseError, parse_junit_xml

SAMPLE_XML = Path(__file__).parent / "sample.xml"

client = TestClient(app)


@pytest.fixture(autouse=True)
def _bypass_auth_for_module(bypass_auth):
    """Automatically bypass API key auth for all tests in this module."""


@pytest.fixture(autouse=True)
def _bypass_embed_task(mock_embed_task):
    """Automatically mock embed task dispatch for all tests in this module."""


# ---------------------------------------------------------------------------
# Parser unit tests
# ---------------------------------------------------------------------------

def test_parse_sample_xml():
    result = parse_junit_xml(SAMPLE_XML.read_bytes())
    assert result.name == "SampleTestSuite"
    assert result.total_tests == 5
    assert result.total_failures == 1
    assert result.total_errors == 1
    assert result.total_skipped == 1
    assert result.elapsed_time == pytest.approx(1.234)
    assert len(result.test_cases) == 5


def test_parse_passed_test():
    result = parse_junit_xml(SAMPLE_XML.read_bytes())
    passed = [tc for tc in result.test_cases if tc.name == "test_addition"]
    assert len(passed) == 1
    assert passed[0].status == "passed"
    assert passed[0].failure_message is None


def test_parse_failed_test():
    result = parse_junit_xml(SAMPLE_XML.read_bytes())
    failed = [tc for tc in result.test_cases if tc.name == "test_multiplication_fails"]
    assert len(failed) == 1
    assert failed[0].status == "failed"
    assert "AssertionError" in (failed[0].failure_message or "")


def test_parse_skipped_test():
    result = parse_junit_xml(SAMPLE_XML.read_bytes())
    skipped = [tc for tc in result.test_cases if tc.name == "test_division_skipped"]
    assert len(skipped) == 1
    assert skipped[0].status == "skipped"
    assert "disabled" in (skipped[0].failure_message or "")


def test_parse_error_test():
    result = parse_junit_xml(SAMPLE_XML.read_bytes())
    errored = [tc for tc in result.test_cases if tc.name == "test_modulo_error"]
    assert len(errored) == 1
    assert errored[0].status == "error"
    assert "RuntimeError" in (errored[0].failure_message or "")


def test_parse_invalid_xml():
    with pytest.raises(JUnitParseError, match="Invalid XML"):
        parse_junit_xml(b"this is not xml")


def test_parse_wrong_root_element():
    with pytest.raises(JUnitParseError, match="Expected root element"):
        parse_junit_xml(b"<root><child/></root>")


def test_parse_missing_name_attribute():
    xml = b'<testsuite tests="1" failures="0" errors="0" skipped="0" time="0.1"><testcase name="t"/></testsuite>'
    with pytest.raises(JUnitParseError, match="missing a 'name' attribute"):
        parse_junit_xml(xml)


def test_parse_testsuites_wrapper():
    xml = b"""<?xml version="1.0"?>
<testsuites>
  <testsuite name="Suite" tests="1" failures="0" errors="0" skipped="0" time="0.5">
    <testcase name="test_one"/>
  </testsuite>
</testsuites>"""
    result = parse_junit_xml(xml)
    assert result.name == "Suite"
    assert result.total_tests == 1


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------

def test_post_results_success(reset_store):
    with SAMPLE_XML.open("rb") as f:
        response = client.post("/results", files={"file": ("sample.xml", f, "application/xml")})
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "SampleTestSuite"
    assert data["total_tests"] == 5
    assert data["total_failures"] == 1
    assert data["total_errors"] == 1
    assert data["total_skipped"] == 1
    assert len(data["test_cases"]) == 5


def test_post_results_invalid_xml(reset_store):
    response = client.post(
        "/results",
        files={"file": ("bad.xml", b"not xml content", "application/xml")},
    )
    assert response.status_code == 422
    assert "Invalid XML" in response.json()["detail"]


def test_post_results_wrong_root(reset_store):
    response = client.post(
        "/results",
        files={"file": ("bad.xml", b"<html><body/></html>", "application/xml")},
    )
    assert response.status_code == 422
    assert "Expected root element" in response.json()["detail"]


def test_get_results_returns_list(reset_store):
    response = client.get("/results")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_results_contains_posted_result(reset_store):
    with SAMPLE_XML.open("rb") as f:
        post_response = client.post("/results", files={"file": ("sample.xml", f, "application/xml")})
    assert post_response.status_code == 200

    response = client.get("/results")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "SampleTestSuite"


def test_get_result_by_index(reset_store):
    with SAMPLE_XML.open("rb") as f:
        post_response = client.post("/results", files={"file": ("sample.xml", f, "application/xml")})
    assert post_response.status_code == 200

    response = client.get("/results/1")
    assert response.status_code == 200
    assert response.json()["name"] == "SampleTestSuite"


def test_get_result_by_index_not_found(reset_store):
    response = client.get("/results/99999")
    assert response.status_code == 404
    assert "No result with id" in response.json()["detail"]


def test_get_result_by_negative_index_not_found(reset_store):
    response = client.get("/results/-1")
    assert response.status_code == 404
    assert "No result with id" in response.json()["detail"]
