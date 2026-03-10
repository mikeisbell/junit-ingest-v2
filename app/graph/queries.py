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
        Dict with keys: bug, affected_features, covering_tests, gap_assessment.
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

        # Aggregate all features and their covering tests in one query so the
        # result is always a single row regardless of how many features a bug
        # affects. Calling .single() on a multi-row result would silently discard
        # coverage data for the extra features.
        coverage_result = session.run(
            """
            MATCH (b:Bug {id: $bug_id})-[:AFFECTS]->(f:Feature)
            OPTIONAL MATCH (t:TestCase)-[:COVERS]->(f)
            WITH f, collect({name: t.name, suite_name: t.suite_name, status: t.status}) AS tests
            RETURN collect({
                feature_name: f.name,
                feature_description: f.description,
                tests: tests
            }) AS features
            """,
            bug_id=bug_id,
        )
        coverage_record = coverage_result.single()
        if coverage_record is None:
            return {"error": "bug not found"}

        # Flatten all tests across all affected features, filtering out null
        # entries that appear when OPTIONAL MATCH finds no test cases for a feature.
        covering_tests = []
        for feat in coverage_record["features"]:
            for t in feat["tests"]:
                if t.get("name") is not None:
                    covering_tests.append(t)

        # Build the affected_features list (one entry per feature this bug affects).
        affected_features = [
            {"name": feat["feature_name"], "description": feat["feature_description"]}
            for feat in coverage_record["features"]
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
            "affected_features": affected_features,
            "covering_tests": covering_tests,
            "gap_assessment": gap_assessment,
        }
