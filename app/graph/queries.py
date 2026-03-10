"""Graph traversal queries for impact-driven test selection and gap analysis.

This module provides two graph traversal use cases:
1. get_tests_for_modules: Given changed code modules, return prioritized test cases
   that cover features implemented in those modules.
2. get_gap_analysis: Given a bug ID, return feature coverage analysis showing which
   test cases cover the feature affected by the bug and the coverage posture.
"""
import logging

from ..logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)


def get_tests_for_modules(driver, module_names: list) -> list:
    """Return test cases that cover features implemented in the given code modules.

    Traversal path: (CodeModule)<-[:IMPLEMENTED_IN]-(Feature)<-[:COVERS]-(TestCase)

    Priority is "high" if the test's parent suite had failures at the time of last
    ingestion — signalling that the area is already fragile. Priority is "normal"
    otherwise. This lets CI systems front-load regression-sensitive tests when a
    recently-failing module changes.

    Args:
        driver:       Neo4j driver. Returns empty list if None (fail-open).
        module_names: List of CodeModule.name values representing changed files.

    Returns:
        List of dicts with keys: test_name, feature_name, module_name, priority.
    """
    if driver is None:
        return []

    with driver.session() as session:
        result = session.run(
            """
            MATCH (m:CodeModule)<-[:IMPLEMENTED_IN]-(f:Feature)<-[:COVERS]-(t:TestCase)
            WHERE m.name IN $module_names
            OPTIONAL MATCH (s:TestSuite)-[:CONTAINS]->(t)
            RETURN t.name AS test_name,
                   f.name AS feature_name,
                   m.name AS module_name,
                   s.total_failures AS suite_failures
            """,
            module_names=module_names,
        )
        tests = []
        seen: set = set()
        for record in result:
            key = (record["test_name"], record["module_name"])
            if key in seen:
                continue
            seen.add(key)
            # A suite with failures signals this test lives in an area of recent
            # instability, so it should run ahead of lower-risk tests.
            priority = "high" if (record["suite_failures"] and record["suite_failures"] > 0) else "normal"
            tests.append({
                "test_name": record["test_name"],
                "feature_name": record["feature_name"],
                "module_name": record["module_name"],
                "priority": priority,
            })
    return tests


def get_gap_analysis(driver, bug_id: str) -> dict:
    """Return a coverage analysis for the feature affected by the given bug.

    Traversal path: (Bug)-[:AFFECTS]->(Feature)<-[:COVERS]-(TestCase)

    The gap_assessment field gives a quick signal about escape risk:
    - "covered":              at least one passing test covers the feature.
    - "gap_detected":         no test cases cover the feature at all.
    - "coverage_unreliable":  tests exist but all have status "failed" or "error",
                              meaning the feature is nominally covered but the
                              tests themselves are not currently green.

    Args:
        driver: Neo4j driver. Returns {"error": "graph unavailable"} if None.
        bug_id: The Bug.id value to look up (e.g. "BUG-001").

    Returns:
        Dict with keys: bug, affected_feature, covering_tests, gap_assessment.
        On failure returns {"error": "..."}.
    """
    if driver is None:
        return {"error": "graph unavailable"}

    with driver.session() as session:
        # Verify the bug exists before traversing its relationships to return
        # a clean "bug not found" error rather than an empty coverage result.
        bug_result = session.run(
            "MATCH (b:Bug {id: $bug_id}) "
            "RETURN b.id AS id, b.title AS title, b.severity AS severity, b.escaped AS escaped",
            bug_id=bug_id,
        )
        bug_record = bug_result.single()
        if bug_record is None:
            return {"error": "bug not found"}

        bug = {
            "id": bug_record["id"],
            "title": bug_record["title"],
            "severity": bug_record["severity"],
            "escaped": bug_record["escaped"],
        }

        # Collect the affected feature and all covering tests in one query to
        # avoid N+1 round-trips when a feature has many covering tests.
        coverage_result = session.run(
            """
            MATCH (b:Bug {id: $bug_id})-[:AFFECTS]->(f:Feature)
            OPTIONAL MATCH (t:TestCase)-[:COVERS]->(f)
            RETURN f.name AS feature_name,
                   f.description AS feature_description,
                   collect({name: t.name, suite_name: t.suite_name, status: t.status}) AS tests
            """,
            bug_id=bug_id,
        )
        coverage_record = coverage_result.single()
        if coverage_record is None:
            return {"error": "bug not found"}

        # Filter out null entries that appear when OPTIONAL MATCH finds no test cases.
        covering_tests = [
            t for t in coverage_record["tests"]
            if t.get("name") is not None
        ]

        # Determine coverage posture to give operators a quick escape-risk signal.
        if not covering_tests:
            gap_assessment = "gap_detected"
        elif all(t.get("status") in ("failed", "error") for t in covering_tests):
            gap_assessment = "coverage_unreliable"
        else:
            gap_assessment = "covered"

        return {
            "bug": bug,
            "affected_feature": {
                "name": coverage_record["feature_name"],
                "description": coverage_record["feature_description"],
            },
            "covering_tests": covering_tests,
            "gap_assessment": gap_assessment,
        }
