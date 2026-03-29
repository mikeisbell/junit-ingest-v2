"""Pre-merge webhook for impact-driven test selection.

Implements POST /webhook/premerge. Receives a list of changed code modules
from a developer's MR, selects tests via the Neo4j knowledge graph, simulates
test execution against fixture data, runs failure analysis, and returns
structured results with a merge recommendation.
"""
import json
import logging
import os

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from .auth import require_api_key
from .bug_tracker import (
    create_bug,
    find_bug_by_signature,
    get_all_bugs,
    link_failure_to_bug,
    set_bug_status,
)
from .graph.driver import get_driver
from .graph.queries import get_tests_for_modules
from .logging_config import configure_logging
from .parser import JUnitParseError, parse_junit_xml

configure_logging()

logger = logging.getLogger(__name__)

router = APIRouter()

P0_REGRESSION_TESTS = [
    "test_checkout_flow",
    "test_payment_gateway",
    "test_user_login",
    "test_order_processing",
]

_FIXTURES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "demo", "data", "premerge_fixtures.json"
)


class PremergeRequest(BaseModel):
    mr_id: str
    author: str
    changed_modules: list[str]
    description: str = ""


class AnalyzeResponse(BaseModel):
    build: str
    suite_name: str
    total_tests: int
    total_failures: int
    total_errors: int
    total_passed: int
    failure_rate: float
    analysis: dict | None
    verified_bugs: list[str]
    merge_recommendation: str


class PremergeResponse(BaseModel):
    mr_id: str
    build: str
    selected_tests: list[dict]
    total_selected: int
    results: list[dict]
    total_run: int
    total_passed: int
    total_failed: int
    failure_rate: float
    analysis: dict | None
    merge_recommendation: str


def _load_fixtures() -> dict:
    """Load premerge_fixtures.json. Returns empty dict and logs warning if missing."""
    if not os.path.exists(_FIXTURES_PATH):
        logger.warning("premerge_fixtures_missing", extra={"path": _FIXTURES_PATH})
        return {}
    with open(_FIXTURES_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _verify_resolved_bugs(test_name: str, build: str) -> list[str]:
    """Find resolved bugs linked to test_name and mark them Verified.

    Returns the list of bug IDs promoted to 'verified'.
    Never raises; logs a warning on unexpected errors.
    """
    verified: list[str] = []
    try:
        for bug in get_all_bugs():
            if (
                test_name in bug.get("linked_test_names", [])
                and bug.get("status") == "resolved"
            ):
                set_bug_status(bug["id"], "verified")
                verified.append(bug["id"])
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "verify_resolved_bugs_error",
            extra={"test_name": test_name, "error": str(exc)},
        )
    return verified


def analyze_failures(failed_results: list[dict], build: str) -> dict:
    """Analyze failed test results, linking or creating bugs for each failure.

    Args:
        failed_results: List of failed result dicts from simulated test execution.
        build:          Build string to associate with discovered bugs.

    Returns:
        Dict with build, total_failures, bugs_linked, bugs_created, bug_ids.
    """
    bugs_linked = 0
    bugs_created = 0
    bug_ids: list[str] = []

    for result in failed_results:
        test_name = result["test_name"]
        failure_message = result.get("failure_message") or ""
        feature = result.get("feature_name")
        priority = result.get("priority", "normal")

        existing = find_bug_by_signature(failure_message)
        if existing is not None:
            link_failure_to_bug(existing["id"], build, test_name)
            bug_ids.append(existing["id"])
            bugs_linked += 1
        else:
            severity = "high" if priority == "high" else "medium"
            new_bug = create_bug(
                title=f"Test failure: {test_name}",
                severity=severity,
                feature=feature,
                failure_signature=failure_message[:120],
                build=build,
                test_name=test_name,
            )
            bug_ids.append(new_bug["id"])
            bugs_created += 1

    logger.info(
        "failure_analysis_complete",
        extra={"build": build, "bugs_linked": bugs_linked, "bugs_created": bugs_created},
    )

    return {
        "build": build,
        "total_failures": len(failed_results),
        "bugs_linked": bugs_linked,
        "bugs_created": bugs_created,
        "bug_ids": bug_ids,
    }


@router.post("/webhook/premerge", response_model=PremergeResponse)
async def premerge_webhook(
    request: PremergeRequest,
    _api_key=Depends(require_api_key),
) -> PremergeResponse:
    """Receive an MR's changed modules, select tests, simulate execution, and
    return results with a merge recommendation."""
    build = "Premerge_MR"
    driver = get_driver()

    # Step 1: Select tests
    graph_tests: list[dict] = get_tests_for_modules(driver, request.changed_modules)

    # Merge graph-selected tests and P0 regression tests (deduplicated)
    seen_names: set[str] = {t["test_name"] for t in graph_tests}
    selected_tests = list(graph_tests)
    for p0_name in P0_REGRESSION_TESTS:
        if p0_name not in seen_names:
            selected_tests.append({
                "test_name": p0_name,
                "feature_name": "p0_regression",
                "module_name": "p0",
                "priority": "high",
            })
            seen_names.add(p0_name)

    total_selected = len(selected_tests)

    # Step 2: Simulate test execution
    fixtures = _load_fixtures()
    results: list[dict] = []
    for test in selected_tests:
        test_name = test["test_name"]
        fixture = fixtures.get(test_name, {"status": "passed", "failure_message": None})
        results.append({
            "test_name": test_name,
            "status": fixture.get("status", "passed"),
            "failure_message": fixture.get("failure_message"),
            "feature_name": test["feature_name"],
            "module_name": test["module_name"],
            "priority": test["priority"],
            "build": build,
        })

    failed_results = [r for r in results if r["status"] == "failed"]
    total_failed = len(failed_results)
    total_passed = len(results) - total_failed
    failure_rate = total_failed / len(results) if results else 0.0

    # Step 3: Run failure analysis if needed
    analysis: dict | None = None
    if failed_results:
        analysis = analyze_failures(failed_results, build)

    merge_recommendation = "blocked" if failed_results else "approved"

    # Step 4: Log and return
    logger.info(
        "premerge_completed",
        extra={
            "mr_id": request.mr_id,
            "author": request.author,
            "total_selected": total_selected,
            "total_failed": total_failed,
            "merge_recommendation": merge_recommendation,
        },
    )

    return PremergeResponse(
        mr_id=request.mr_id,
        build=build,
        selected_tests=selected_tests,
        total_selected=total_selected,
        results=results,
        total_run=len(results),
        total_passed=total_passed,
        total_failed=total_failed,
        failure_rate=failure_rate,
        analysis=analysis,
        merge_recommendation=merge_recommendation,
    )

@router.post("/webhook/analyze", response_model=AnalyzeResponse)
async def analyze_webhook(
    file: UploadFile = File(...),
    build: str = Query(...),
    _api_key=Depends(require_api_key),
) -> AnalyzeResponse:
    """Accept a JUnit XML upload and build string, parse results, run failure
    analysis, and verify resolved bugs whose covering tests now pass."""

    # Step 1: Parse XML
    content = await file.read()
    try:
        suite = parse_junit_xml(content)
    except JUnitParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Step 2: Partition results
    failed_results: list[dict] = []
    passed_cases = []
    for tc in suite.test_cases:
        if tc.status in ("failed", "error"):
            failed_results.append({
                "test_name": tc.name,
                "status": tc.status,
                "failure_message": tc.failure_message,
                "feature_name": None,
                "module_name": None,
                "priority": "normal",
                "build": build,
            })
        elif tc.status == "passed":
            passed_cases.append(tc)

    # Step 3: Run failure analysis
    analysis: dict | None = None
    if failed_results:
        analysis = analyze_failures(failed_results, build)

    # Step 4: Verified resolution
    verified_set: set[str] = set()
    for tc in passed_cases:
        for bug_id in _verify_resolved_bugs(tc.name, build):
            verified_set.add(bug_id)
    verified_bugs = list(verified_set)

    total_failures = len(failed_results)
    total_passed = len(passed_cases)
    failure_rate = total_failures / suite.total_tests if suite.total_tests > 0 else 0.0
    merge_recommendation = "blocked" if failed_results else "approved"

    # Step 5: Log and return
    logger.info(
        "analyze_completed",
        extra={
            "build": build,
            "suite_name": suite.name,
            "total_failures": total_failures,
            "verified_bugs": len(verified_bugs),
            "merge_recommendation": merge_recommendation,
        },
    )

    return AnalyzeResponse(
        build=build,
        suite_name=suite.name,
        total_tests=suite.total_tests,
        total_failures=total_failures,
        total_errors=suite.total_errors,
        total_passed=total_passed,
        failure_rate=failure_rate,
        analysis=analysis,
        verified_bugs=verified_bugs,
        merge_recommendation=merge_recommendation,
    )