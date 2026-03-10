"""JUnit test suite ingestion into the Neo4j knowledge graph.

This module handles the ingestion of parsed test suites into the graph.
MERGE semantics are used throughout so re-ingesting the same suite is
idempotent — properties are updated in place rather than creating duplicates.
The feature_map parameter is required and controls which COVERS relationships
are created. If feature_map is empty, no COVERS relationships are created.
"""
import logging

from ..logging_config import configure_logging
from ..models import TestSuiteResult

configure_logging()

logger = logging.getLogger(__name__)


def ingest_suite_to_graph(driver, suite: TestSuiteResult, feature_map: dict) -> None:
    """Ingest a parsed test suite into the Neo4j knowledge graph.

    Creates or merges a TestSuite node and one TestCase node per test case.
    CONTAINS relationships link the suite to each test case. If a test case name
    appears in feature_map, a COVERS relationship is created to the corresponding
    Feature node, making the test discoverable via graph traversal from a code module.

    MERGE (not CREATE) is used throughout so re-ingesting the same suite name is
    idempotent — properties are updated in place rather than creating duplicates.

    Args:
        driver:      Neo4j driver. If None, logs a warning and returns without raising.
        suite:       Parsed TestSuiteResult from the JUnit ingestion pipeline.
        feature_map: Dict mapping test case name -> feature name.
    """
    if driver is None:
        # Graph is optional; skip silently to preserve fail-open behavior for
        # the POST /results endpoint when Neo4j is not running.
        logger.warning("neo4j_ingest_skipped_driver_none")
        return

    with driver.session() as session:
        # Upsert the TestSuite node so re-ingesting the same suite name updates
        # its aggregate counts rather than creating a duplicate node.
        session.run(
            """
            MERGE (s:TestSuite {name: $name})
            SET s.total_tests = $total_tests, s.total_failures = $total_failures
            """,
            name=suite.name,
            total_tests=suite.total_tests,
            total_failures=suite.total_failures,
        )

        for tc in suite.test_cases:
            # Upsert each TestCase and link it to its parent suite.
            session.run(
                """
                MERGE (t:TestCase {name: $name})
                SET t.suite_name = $suite_name, t.status = $status
                WITH t
                MATCH (s:TestSuite {name: $suite_name})
                MERGE (s)-[:CONTAINS]->(t)
                """,
                name=tc.name,
                suite_name=suite.name,
                status=tc.status,
            )
            # Create a COVERS relationship if the test maps to a known feature,
            # enabling downstream graph traversal from code modules to tests.
            feature_name = feature_map.get(tc.name)
            if feature_name:
                session.run(
                    """
                    MATCH (t:TestCase {name: $test_name})
                    MERGE (f:Feature {name: $feature_name})
                    MERGE (t)-[:COVERS]->(f)
                    """,
                    test_name=tc.name,
                    feature_name=feature_name,
                )

    logger.info(
        "neo4j_suite_ingested",
        extra={"suite_name": suite.name, "test_count": len(suite.test_cases)},
    )
