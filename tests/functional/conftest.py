import os

import pytest
import requests


@pytest.fixture(scope="session")
def service_url():
    return os.environ.get("SERVICE_URL", "http://localhost:8001")


@pytest.fixture(scope="session")
def api_key():
    key = os.environ.get("API_KEY")
    if not key:
        pytest.skip("API_KEY environment variable not set")
    return key


@pytest.fixture(scope="session")
def auth_headers(api_key):
    return {"Authorization": f"Bearer {api_key}"}


@pytest.fixture(scope="session")
def ingested_suite(service_url, auth_headers):
    xml_path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "test.xml")
    with open(xml_path, "rb") as f:
        xml_content = f.read()
    response = requests.post(
        f"{service_url}/results",
        files={"file": ("test.xml", xml_content, "application/xml")},
        headers=auth_headers,
    )
    return response.json()


@pytest.fixture
def known_failure_xml():
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<testsuite name="KnownFailureSuite" tests="1" failures="1" errors="0" skipped="0" time="0.1">'
        '<testcase classname="com.example.DiscountTest" name="test_calculate_discount" time="0.1">'
        "<failure type=\"ZeroDivisionError\">"
        "ZeroDivisionError: division by zero in calculate_discount function"
        "</failure>"
        "</testcase>"
        "</testsuite>"
    )
