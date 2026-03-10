"""Unit tests for app/graph/queries.py.

All tests use mocked Neo4j drivers and sessions. No live Neo4j instance required.
"""
from unittest.mock import MagicMock

from app.graph.queries import get_gap_analysis, get_tests_for_modules


# ─── shared helpers ───────────────────────────────────────────────────────────


def make_mock_driver():
    """Return a (mock_driver, mock_session) pair wired for context-manager use."""
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    return mock_driver, mock_session


def make_record(test_name="test_checkout", feature_name="checkout",
                module_name="cart.py", suite_failures=0):
    """Build a mock Neo4j record for get_tests_for_modules results."""
    data = {
        "test_name": test_name,
        "feature_name": feature_name,
        "module_name": module_name,
        "suite_failures": suite_failures,
    }
    record = MagicMock()
    record.__getitem__ = lambda self, key: data[key]
    return record


def make_mock_result(records):
    """Wrap a list of records in an iterable mock result."""
    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter(records))
    return mock_result


def _make_bug_record(bug_id="BUG-001", title="Cart crash", severity="high", escaped=True):
    """Build a mock Neo4j record representing a Bug node."""
    data = {"id": bug_id, "title": title, "severity": severity, "escaped": escaped}
    record = MagicMock()
    record.__getitem__ = lambda self, key: data[key]
    return record


def _make_coverage_record(feature_name="checkout", feature_description="Handles payment",
                           tests=None):
    """Build a mock Neo4j record representing the aggregated coverage query result.

    The new query returns a single row with a 'features' key containing a list
    of feature dicts so that bugs affecting multiple features are handled without
    triggering the 'Expected single record, found multiple' Neo4j warning.
    """
    data = {
        "features": [
            {
                "feature_name": feature_name,
                "feature_description": feature_description,
                "tests": tests if tests is not None else [],
            }
        ],
    }
    record = MagicMock()
    record.__getitem__ = lambda self, key: data[key]
    return record


def _make_gap_side_effect(tests=None):
    """Return a two-element side_effect list for two sequential session.run() calls."""
    run1 = MagicMock()
    run1.single.return_value = _make_bug_record()
    run2 = MagicMock()
    run2.single.return_value = _make_coverage_record(tests=tests if tests is not None else [])
    return [run1, run2]


# ─── get_tests_for_modules ────────────────────────────────────────────────────


def test_get_tests_for_modules_returns_empty_when_driver_none():
    """Passing None as driver should return [] immediately without raising (fail-open guard)."""
    result = get_tests_for_modules(None, ["cart.py"])
    assert result == []


def test_get_tests_for_modules_returns_empty_when_no_records():
    """When the session returns no records the function should return an empty list."""
    mock_driver, mock_session = make_mock_driver()
    mock_session.run.return_value = make_mock_result([])
    result = get_tests_for_modules(mock_driver, ["cart.py"])
    assert result == []


def test_get_tests_for_modules_returns_results():
    """Two distinct records should produce a two-item list each with the expected keys."""
    mock_driver, mock_session = make_mock_driver()
    records = [
        make_record("test_checkout", "checkout", "cart.py", suite_failures=1),
        make_record("test_login", "auth", "auth.py", suite_failures=0),
    ]
    mock_session.run.return_value = make_mock_result(records)
    result = get_tests_for_modules(mock_driver, ["cart.py", "auth.py"])
    assert len(result) == 2
    for item in result:
        assert set(item.keys()) == {"test_name", "feature_name", "module_name", "priority"}


def test_get_tests_for_modules_priority_high_when_suite_has_failures():
    """A record with suite_failures > 0 should produce priority = 'high'."""
    mock_driver, mock_session = make_mock_driver()
    mock_session.run.return_value = make_mock_result([
        make_record("test_checkout", "checkout", "cart.py", suite_failures=3)
    ])
    result = get_tests_for_modules(mock_driver, ["cart.py"])
    assert result[0]["priority"] == "high"


def test_get_tests_for_modules_priority_normal_when_no_failures():
    """A record with suite_failures = 0 should produce priority = 'normal'."""
    mock_driver, mock_session = make_mock_driver()
    mock_session.run.return_value = make_mock_result([
        make_record("test_checkout", "checkout", "cart.py", suite_failures=0)
    ])
    result = get_tests_for_modules(mock_driver, ["cart.py"])
    assert result[0]["priority"] == "normal"


def test_get_tests_for_modules_priority_normal_when_suite_failures_none():
    """A record where suite_failures = None should produce priority = 'normal' (falsy guard)."""
    mock_driver, mock_session = make_mock_driver()
    mock_session.run.return_value = make_mock_result([
        make_record("test_checkout", "checkout", "cart.py", suite_failures=None)
    ])
    result = get_tests_for_modules(mock_driver, ["cart.py"])
    assert result[0]["priority"] == "normal"


def test_get_tests_for_modules_deduplicates_by_test_and_module():
    """Two records with identical (test_name, module_name) should collapse to one result."""
    mock_driver, mock_session = make_mock_driver()
    records = [
        make_record("test_checkout", "checkout", "cart.py", suite_failures=0),
        make_record("test_checkout", "checkout", "cart.py", suite_failures=1),
    ]
    mock_session.run.return_value = make_mock_result(records)
    result = get_tests_for_modules(mock_driver, ["cart.py"])
    assert len(result) == 1


# ─── get_gap_analysis ─────────────────────────────────────────────────────────


def test_get_gap_analysis_returns_error_when_driver_none():
    """Passing None as driver should return {'error': 'graph unavailable'}."""
    result = get_gap_analysis(None, "BUG-001")
    assert result == {"error": "graph unavailable"}


def test_get_gap_analysis_returns_error_when_bug_not_found():
    """When the first session.run().single() returns None the bug does not exist."""
    mock_driver, mock_session = make_mock_driver()
    run1 = MagicMock()
    run1.single.return_value = None
    mock_session.run.side_effect = [run1]
    result = get_gap_analysis(mock_driver, "BUG-999")
    assert result == {"error": "bug not found"}


def test_get_gap_analysis_returns_error_when_coverage_record_none():
    """When the bug exists but coverage query returns None, result is 'bug not found'."""
    mock_driver, mock_session = make_mock_driver()
    run1 = MagicMock()
    run1.single.return_value = _make_bug_record()
    run2 = MagicMock()
    run2.single.return_value = None
    mock_session.run.side_effect = [run1, run2]
    result = get_gap_analysis(mock_driver, "BUG-001")
    assert result == {"error": "bug not found"}


def test_get_gap_analysis_gap_detected_when_no_covering_tests():
    """A coverage record with an empty tests list should yield gap_assessment = 'gap_detected'."""
    mock_driver, mock_session = make_mock_driver()
    mock_session.run.side_effect = _make_gap_side_effect(tests=[])
    result = get_gap_analysis(mock_driver, "BUG-001")
    assert result["gap_assessment"] == "gap_detected"


def test_get_gap_analysis_covered_when_passing_test_exists():
    """At least one passing test should yield gap_assessment = 'covered'."""
    mock_driver, mock_session = make_mock_driver()
    mock_session.run.side_effect = _make_gap_side_effect(tests=[
        {"name": "test_checkout", "suite_name": "CartSuite", "status": "passed"}
    ])
    result = get_gap_analysis(mock_driver, "BUG-001")
    assert result["gap_assessment"] == "covered"


def test_get_gap_analysis_coverage_unreliable_when_all_tests_failed():
    """All tests with status='failed' should yield gap_assessment = 'coverage_unreliable'."""
    mock_driver, mock_session = make_mock_driver()
    mock_session.run.side_effect = _make_gap_side_effect(tests=[
        {"name": "test_checkout", "suite_name": "CartSuite", "status": "failed"},
        {"name": "test_payment", "suite_name": "CartSuite", "status": "failed"},
    ])
    result = get_gap_analysis(mock_driver, "BUG-001")
    assert result["gap_assessment"] == "coverage_unreliable"


def test_get_gap_analysis_coverage_unreliable_when_all_tests_error():
    """All tests with status='error' should yield gap_assessment = 'coverage_unreliable'."""
    mock_driver, mock_session = make_mock_driver()
    mock_session.run.side_effect = _make_gap_side_effect(tests=[
        {"name": "test_checkout", "suite_name": "CartSuite", "status": "error"},
    ])
    result = get_gap_analysis(mock_driver, "BUG-001")
    assert result["gap_assessment"] == "coverage_unreliable"


def test_get_gap_analysis_filters_null_test_entries():
    """A test entry with name=None (from OPTIONAL MATCH with no match) is filtered before assessment."""
    mock_driver, mock_session = make_mock_driver()
    mock_session.run.side_effect = _make_gap_side_effect(tests=[
        {"name": None, "suite_name": None, "status": None},
    ])
    result = get_gap_analysis(mock_driver, "BUG-001")
    assert result["gap_assessment"] == "gap_detected"


def test_get_gap_analysis_returns_correct_top_level_keys():
    """Return dict must have exactly the keys: bug, affected_features, covering_tests, gap_assessment."""
    mock_driver, mock_session = make_mock_driver()
    mock_session.run.side_effect = _make_gap_side_effect(tests=[
        {"name": "test_checkout", "suite_name": "CartSuite", "status": "passed"}
    ])
    result = get_gap_analysis(mock_driver, "BUG-001")
    assert set(result.keys()) == {"bug", "affected_features", "covering_tests", "gap_assessment"}


def test_get_gap_analysis_bug_dict_has_correct_keys():
    """The 'bug' sub-dict must have exactly the keys: id, title, severity, escaped."""
    mock_driver, mock_session = make_mock_driver()
    mock_session.run.side_effect = _make_gap_side_effect(tests=[
        {"name": "test_checkout", "suite_name": "CartSuite", "status": "passed"}
    ])
    result = get_gap_analysis(mock_driver, "BUG-001")
    assert set(result["bug"].keys()) == {"id", "title", "severity", "escaped"}


def test_get_gap_analysis_affected_feature_has_correct_keys():
    """Each item in 'affected_features' must have exactly the keys: name, description."""
    mock_driver, mock_session = make_mock_driver()
    mock_session.run.side_effect = _make_gap_side_effect(tests=[
        {"name": "test_checkout", "suite_name": "CartSuite", "status": "passed"}
    ])
    result = get_gap_analysis(mock_driver, "BUG-001")
    assert isinstance(result["affected_features"], list)
    assert set(result["affected_features"][0].keys()) == {"name", "description"}


def test_get_gap_analysis_returns_list_of_affected_features():
    """'affected_features' must be a non-empty list when the bug has at least one affected feature."""
    mock_driver, mock_session = make_mock_driver()
    mock_session.run.side_effect = _make_gap_side_effect(tests=[
        {"name": "test_checkout", "suite_name": "CartSuite", "status": "passed"}
    ])
    result = get_gap_analysis(mock_driver, "BUG-001")
    assert isinstance(result["affected_features"], list)
    assert len(result["affected_features"]) >= 1
