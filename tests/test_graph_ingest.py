"""Unit tests for app/graph/ingest.py.

All tests use mocked Neo4j drivers and sessions. No live Neo4j instance required.
"""
from unittest.mock import MagicMock

from app.graph.ingest import ingest_suite_to_graph
from app.models import TestCase, TestSuiteResult


# ─── shared helpers ───────────────────────────────────────────────────────────


def make_mock_driver():
    """Return a (mock_driver, mock_session) pair wired for context-manager use."""
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    return mock_driver, mock_session


def make_suite(name="ExampleSuite", test_cases=None):
    """Build a minimal TestSuiteResult for ingest tests.

    Uses the actual field names from app.models: elapsed_time (not time),
    and TestCase requires only name and status.
    """
    if test_cases is None:
        test_cases = [
            TestCase(name="test_one", status="passed"),
            TestCase(name="test_two", status="failed", failure_message="assert False"),
        ]
    return TestSuiteResult(
        name=name,
        total_tests=len(test_cases),
        total_failures=sum(1 for t in test_cases if t.status == "failed"),
        total_errors=0,
        total_skipped=0,
        elapsed_time=1.0,
        test_cases=test_cases,
    )


# ─── tests ────────────────────────────────────────────────────────────────────


def test_ingest_suite_skips_when_driver_none():
    """Passing None as driver should return without raising (fail-open guard)."""
    ingest_suite_to_graph(None, make_suite(), {})  # must not raise


def test_ingest_suite_creates_suite_node():
    """ingest_suite_to_graph must issue at least one session.run call referencing 'TestSuite'."""
    mock_driver, mock_session = make_mock_driver()
    ingest_suite_to_graph(mock_driver, make_suite(), {})
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    assert any("TestSuite" in q for q in queries)


def test_ingest_suite_uses_merge_for_suite_node():
    """The TestSuite node query must use MERGE to ensure idempotent upsert semantics."""
    mock_driver, mock_session = make_mock_driver()
    ingest_suite_to_graph(mock_driver, make_suite(), {})
    suite_queries = [
        call.args[0]
        for call in mock_session.run.call_args_list
        if "TestSuite" in call.args[0]
    ]
    assert len(suite_queries) >= 1
    assert all("MERGE" in q for q in suite_queries)


def test_ingest_suite_creates_test_case_node_for_each_test():
    """A suite with two test cases should produce at least two session.run calls containing 'TestCase'."""
    mock_driver, mock_session = make_mock_driver()
    ingest_suite_to_graph(mock_driver, make_suite(), {})
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    testcase_queries = [q for q in queries if "TestCase" in q]
    assert len(testcase_queries) >= 2


def test_ingest_suite_creates_contains_relationship():
    """At least one session.run call must create the CONTAINS relationship between suite and test case."""
    mock_driver, mock_session = make_mock_driver()
    ingest_suite_to_graph(mock_driver, make_suite(), {})
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    assert any("CONTAINS" in q for q in queries)


def test_ingest_suite_creates_covers_when_feature_map_matches():
    """A test case whose name is in feature_map should produce a COVERS relationship call."""
    mock_driver, mock_session = make_mock_driver()
    suite = make_suite(test_cases=[TestCase(name="test_checkout", status="passed")])
    ingest_suite_to_graph(mock_driver, suite, {"test_checkout": "checkout"})
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    assert any("COVERS" in q for q in queries)


def test_ingest_suite_skips_covers_when_no_feature_map_match():
    """When a test case name is absent from feature_map, no COVERS call is issued."""
    mock_driver, mock_session = make_mock_driver()
    suite = make_suite(test_cases=[TestCase(name="test_unknown", status="passed")])
    ingest_suite_to_graph(mock_driver, suite, {})
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    assert not any("COVERS" in q for q in queries)


def test_ingest_suite_handles_empty_test_cases():
    """A suite with no test cases should issue exactly one session.run call (the suite node only)."""
    mock_driver, mock_session = make_mock_driver()
    suite = make_suite(test_cases=[])
    ingest_suite_to_graph(mock_driver, suite, {})
    assert mock_session.run.call_count == 1


def test_ingest_suite_handles_multiple_feature_map_matches():
    """Two test cases both present in feature_map should each produce one COVERS relationship call."""
    mock_driver, mock_session = make_mock_driver()
    suite = make_suite(test_cases=[
        TestCase(name="test_checkout", status="passed"),
        TestCase(name="test_payment", status="passed"),
    ])
    ingest_suite_to_graph(mock_driver, suite, {
        "test_checkout": "checkout",
        "test_payment": "payment",
    })
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    covers_queries = [q for q in queries if "COVERS" in q]
    assert len(covers_queries) == 2
