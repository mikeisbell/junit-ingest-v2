#!/usr/bin/env python3
"""Ingest demo test results into the running junit-ingest-v2 service.

Run this script after seeding the graph to populate the service with
realistic test failure data for the demo environment.

Usage:
    API_KEY=your-key python demo/ingest.py

Environment variables required:
    API_KEY        Bearer token issued via POST /keys
    SERVICE_URL    (default: http://localhost:8001)
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

from app.graph.driver import get_driver
from app.graph.ingest import ingest_suite_to_graph
from app.parser import parse_junit_xml

SERVICE_URL = os.getenv("SERVICE_URL", "http://localhost:8001")
API_KEY = os.getenv("API_KEY", "")
DEMO_XML_PATH = os.path.join(os.path.dirname(__file__), "data", "demo.xml")


def main():
    if not API_KEY:
        print("ERROR: API_KEY environment variable not set.")
        sys.exit(1)

    with open(DEMO_XML_PATH, "rb") as f:
        xml_content = f.read()

    suite_result = parse_junit_xml(xml_content)

    driver = get_driver()
    if driver:
        feature_map_path = Path(__file__).parent / "data" / "feature_map.json"
        with open(feature_map_path) as f:
            feature_map = json.load(f)
        ingest_suite_to_graph(driver, suite_result, feature_map)
        driver.close()
    else:
        print("Neo4j unavailable, skipping graph ingest")

    boundary = "----DemoIngestBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="demo.xml"\r\n'
        f"Content-Type: application/xml\r\n\r\n"
    ).encode() + xml_content + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{SERVICE_URL}/webhook/ci",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )

    with urllib.request.urlopen(req) as resp:
        print(f"Status: {resp.status}")
        print(resp.read().decode())


if __name__ == "__main__":
    main()
