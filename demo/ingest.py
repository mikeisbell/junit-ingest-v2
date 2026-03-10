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
import os
import sys
import urllib.request

SERVICE_URL = os.getenv("SERVICE_URL", "http://localhost:8001")
API_KEY = os.getenv("API_KEY", "")
DEMO_XML_PATH = os.path.join(os.path.dirname(__file__), "data", "demo.xml")


def main():
    if not API_KEY:
        print("ERROR: API_KEY environment variable not set.")
        sys.exit(1)

    with open(DEMO_XML_PATH, "rb") as f:
        xml_content = f.read()

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
