"""
Retrieval evaluation script.

Run manually after the Docker stack is up and test data has been ingested:
    python tests/eval/eval_retrieval.py
"""

import os

import requests

SERVICE_URL = os.getenv("SERVICE_URL", "http://localhost:8001")

EVAL_CASES = [
    {
        "query": "assertion errors where expected value did not match actual",
        "expected_keywords": ["AssertionError", "Expected", "assert"],
    },
    {
        "query": "null pointer or attribute errors",
        "expected_keywords": ["NullPointer", "AttributeError", "null", "None"],
    },
    {
        "query": "timeout or connection failures",
        "expected_keywords": ["timeout", "Timeout", "connection", "Connection"],
    },
]


def run_eval() -> None:
    passed = 0
    total = len(EVAL_CASES)

    for case in EVAL_CASES:
        query = case["query"]
        keywords = case["expected_keywords"]

        response = requests.get(
            f"{SERVICE_URL}/search",
            params={"q": query, "n": 5},
            timeout=10,
        )
        response.raise_for_status()
        results = response.json().get("results", [])

        matched = sum(
            1
            for r in results
            if any(
                kw.lower() in (r.get("failure_message") or "").lower()
                for kw in keywords
            )
        )

        if matched > 0:
            passed += 1
            print(f"PASS [{query}] — {matched}/{len(results)} results matched keywords")
        else:
            print(f"FAIL [{query}] — 0/{len(results)} results matched keywords")

    print(f"\nRetrieval eval complete: {passed}/{total} passed")


if __name__ == "__main__":
    run_eval()
