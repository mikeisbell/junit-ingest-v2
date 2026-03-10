# INSTRUCTIONS_GRAPH_COVERAGE.md

## Goal

Add unit tests for the app/graph/ subpackage modules to restore and exceed the
80% coverage threshold. The new graph modules were added in the modular refactor
but have no unit tests yet, which dropped overall coverage from 79% to 75%.

All tests must use mocked Neo4j drivers and sessions. Do not require a live
Neo4j instance. All mocking must use unittest.mock.MagicMock.

---

## Constraints

- Do not modify any existing test files.
- Do not modify any application code.
- Do not add any new dependencies.
- Every test function must have a docstring explaining what it is testing and why.
- Use pytest fixtures for shared setup where appropriate.
- After all tests are added, overall coverage must reach at least 80%.
- Update pytest.ini to set --cov-fail-under=80 once 80% is confirmed.

---

## Helper: how to mock a Neo4j driver

Use this pattern everywhere a mock driver is needed:

```python
from unittest.mock import MagicMock

def make_mock_driver():
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    return mock_driver, mock_session
```

When a test needs session.run() to return iterable records, configure it like this:

```python
record = MagicMock()
record.__getitem__ = lambda self, key: {
    "test_name": "test_checkout",
    "feature_name": "checkout",
    "module_name": "cart.py",
    "suite_failures": 2,
}[key]

mock_result = MagicMock()
mock_result.__iter__ = MagicMock(return_value=iter([record]))
mock_session.run.return_value = mock_result
```

When a test needs session.run().single() to return different values on two
sequential calls (as in get_gap_analysis which calls session.run twice in the
same session), use side_effect on session.run to return different result objects:

```python
bug_record = MagicMock()
bug_record.__getitem__ = lambda self, key: {
    "id": "BUG-001",
    "title": "Cart crash",
    "severity": "high",
    "escaped": True,
}[key]

covering_test = {"name": "test_checkout", "suite_name": "CartSuite", "status": "passed"}
coverage_record = MagicMock()
coverage_record.__getitem__ = lambda self, key: {
    "feature_name": "checkout",
    "feature_description": "Handles payment",
    "tests": [covering_test],
}[key]

run1 = MagicMock()
run1.single.return_value = bug_record
run2 = MagicMock()
run2.single.return_value = coverage_record
mock_session.run.side_effect = [run1, run2]
```

---

## Helper: how to build TestSuiteResult fixtures

Import from app.models and check that field names match exactly:

```python
from app.models import TestSuiteResult, TestCase
```

Build a minimal suite like this:

```python
def make_suite(name="ExampleSuite", test_cases=None):
    if test_cases is None:
        test_cases = [
            TestCase(name="test_one", status="passed", classname="cls", time=0.1),
            TestCase(name="test_two", status="failed", classname="cls", time=0.2,
                     failure_message="assert False"),
        ]
    return TestSuiteResult(
        name=name,
        total_tests=len(test_cases),
        total_failures=sum(1 for t in test_cases if t.status == "failed"),
        total_errors=0,
        total_skipped=0,
        time=1.0,
        test_cases=test_cases,
    )
```

Before writing fixtures, open app/models.py and verify the exact field names
on TestCase and TestSuiteResult. Adjust the fixture if the actual fields differ.

---

## Step 1: Create tests/test_graph_queries.py

This file tests app/graph/queries.py. Target lines: 38-67, 93-142.

```python
from app.graph.queries import get_tests_for_modules, get_gap_analysis
```

### Tests to implement

**test_get_tests_for_modules_returns_empty_when_driver_none**
Call get_tests_for_modules(None, ["cart.py"]).
Assert the return value is [].

**test_get_tests_for_modules_returns_empty_when_no_records**
Build a mock driver whose session.run returns an empty iterator.
Call get_tests_for_modules(driver, ["cart.py"]).
Assert the return value is [].

**test_get_tests_for_modules_returns_results**
Build a mock driver whose session.run returns two records with distinct
(test_name, module_name) pairs. Include suite_failures > 0 on one record
and suite_failures = 0 on the other.
Assert the returned list has two items.
Assert each item has keys: test_name, feature_name, module_name, priority.

**test_get_tests_for_modules_priority_high_when_suite_has_failures**
Build a mock driver whose session.run returns one record where suite_failures = 3.
Assert the returned item has priority = "high".

**test_get_tests_for_modules_priority_normal_when_no_failures**
Build a mock driver whose session.run returns one record where suite_failures = 0.
Assert the returned item has priority = "normal".

**test_get_tests_for_modules_priority_normal_when_suite_failures_none**
Build a mock driver whose session.run returns one record where suite_failures = None.
Assert the returned item has priority = "normal".

**test_get_tests_for_modules_deduplicates_by_test_and_module**
Build a mock driver whose session.run returns two records with identical
test_name and module_name values (duplicate keys).
Assert the returned list has only one item.

**test_get_gap_analysis_returns_error_when_driver_none**
Call get_gap_analysis(None, "BUG-001").
Assert the return value is {"error": "graph unavailable"}.

**test_get_gap_analysis_returns_error_when_bug_not_found**
Build a mock driver. Set the first session.run call's .single() to return None.
Call get_gap_analysis(driver, "BUG-999").
Assert the return value is {"error": "bug not found"}.

**test_get_gap_analysis_returns_error_when_coverage_record_none**
Build a mock driver. Set the first session.run().single() to return a valid
bug_record and the second session.run().single() to return None.
Call get_gap_analysis(driver, "BUG-001").
Assert the return value is {"error": "bug not found"}.

**test_get_gap_analysis_gap_detected_when_no_covering_tests**
Build a mock driver with a valid bug_record and a coverage_record where
tests = [] (empty list).
Assert the result has gap_assessment = "gap_detected".

**test_get_gap_analysis_covered_when_passing_test_exists**
Build a mock driver with a valid bug_record and a coverage_record where
tests contains one entry with status = "passed".
Assert the result has gap_assessment = "covered".

**test_get_gap_analysis_coverage_unreliable_when_all_tests_failed**
Build a mock driver with a valid bug_record and a coverage_record where
tests contains two entries, both with status = "failed".
Assert the result has gap_assessment = "coverage_unreliable".

**test_get_gap_analysis_coverage_unreliable_when_all_tests_error**
Build a mock driver with a valid bug_record and a coverage_record where
tests contains one entry with status = "error".
Assert the result has gap_assessment = "coverage_unreliable".

**test_get_gap_analysis_filters_null_test_entries**
Build a mock driver with a valid bug_record and a coverage_record where
tests contains one entry where name = None. This simulates what the Neo4j
OPTIONAL MATCH returns when no TestCase covers the feature.
Assert the result has gap_assessment = "gap_detected" because the null
entry is filtered out before the gap assessment is computed.

**test_get_gap_analysis_returns_correct_top_level_keys**
Build a mock driver with a full valid response including a passing test.
Assert the return dict has exactly these keys: bug, affected_feature,
covering_tests, gap_assessment.

**test_get_gap_analysis_bug_dict_has_correct_keys**
Using the same full valid response, assert bug has keys: id, title, severity, escaped.

**test_get_gap_analysis_affected_feature_has_correct_keys**
Using the same full valid response, assert affected_feature has keys: name, description.

---

## Step 2: Create tests/test_graph_seed.py

This file tests app/graph/seed.py. Target lines: 37-86.

IMPORTANT: seed_graph does not guard against driver=None. Do not write a test
for driver=None. All tests must pass a real mock driver.

```python
from app.graph.seed import seed_graph
```

### Shared fixture

```python
@pytest.fixture
def full_seed_data():
    return {
        "modules": [{"name": "cart.py", "path": "src/cart.py"}],
        "features": [{"name": "checkout", "description": "Handles checkout flow"}],
        "feature_module_edges": [{"feature": "checkout", "module": "cart.py"}],
        "bugs": [{"id": "BUG-001", "title": "Cart crash", "severity": "high", "escaped": True}],
        "bug_feature_edges": [{"bug_id": "BUG-001", "feature": "checkout"}],
    }
```

### Tests to implement

**test_seed_graph_runs_all_five_node_and_edge_types**
Call seed_graph with a mock driver and full_seed_data.
Assert session.run was called exactly 5 times (one module, one feature, one
feature_module_edge, one bug, one bug_feature_edge).

**test_seed_graph_creates_codemodule_node**
Capture all session.run call args using mock_session.run.call_args_list.
Assert at least one call's first positional argument contains "CodeModule".

**test_seed_graph_creates_feature_node**
Assert at least one session.run call argument contains "Feature".

**test_seed_graph_creates_implemented_in_relationship**
Assert at least one session.run call argument contains "IMPLEMENTED_IN".

**test_seed_graph_creates_bug_node**
Assert at least one session.run call argument contains "Bug".

**test_seed_graph_creates_affects_relationship**
Assert at least one session.run call argument contains "AFFECTS".

**test_seed_graph_uses_merge_not_bare_create**
For every session.run call, assert that if the query contains "CREATE" it also
contains "MERGE". This verifies idempotency: no bare CREATE statements exist.

**test_seed_graph_handles_empty_seed_data**
Call seed_graph with a mock driver and an empty dict {}.
Assert no exception is raised.
Assert session.run was not called.

**test_seed_graph_handles_partial_seed_data_modules_only**
Call seed_graph with a mock driver and seed_data containing only a modules list
with one entry.
Assert session.run was called exactly once.
Assert no session.run call contained "Feature", "Bug", "IMPLEMENTED_IN", or "AFFECTS".

**test_seed_graph_handles_multiple_modules**
Call seed_graph with a mock driver and seed_data containing three modules.
Assert session.run was called exactly 3 times.

---

## Step 3: Create tests/test_graph_ingest.py

This file tests app/graph/ingest.py. Target lines: 41-82.

```python
from app.graph.ingest import ingest_suite_to_graph
from app.models import TestSuiteResult, TestCase
```

### Tests to implement

**test_ingest_suite_skips_when_driver_none**
Call ingest_suite_to_graph(None, make_suite(), {}).
Assert no exception is raised.

**test_ingest_suite_creates_suite_node**
Call ingest_suite_to_graph with a mock driver, make_suite(), and empty feature_map.
Assert at least one session.run call argument contained "TestSuite".

**test_ingest_suite_uses_merge_for_suite_node**
Assert the session.run call for the TestSuite node contained "MERGE".

**test_ingest_suite_creates_test_case_node_for_each_test**
Call ingest_suite_to_graph with a mock driver and a suite with two test cases.
Assert at least two session.run calls contained "TestCase".

**test_ingest_suite_creates_contains_relationship**
Assert at least one session.run call argument contained "CONTAINS".

**test_ingest_suite_creates_covers_when_feature_map_matches**
Build a suite with one test case named "test_checkout".
Call ingest_suite_to_graph with feature_map = {"test_checkout": "checkout"}.
Assert at least one session.run call argument contained "COVERS".

**test_ingest_suite_skips_covers_when_no_feature_map_match**
Build a suite with one test case named "test_unknown".
Call ingest_suite_to_graph with feature_map = {}.
Assert no session.run call contained "COVERS".

**test_ingest_suite_handles_empty_test_cases**
Call ingest_suite_to_graph with a suite where test_cases = [].
Assert no exception is raised.
Assert exactly one session.run call was made (for the suite node only, no
test case nodes and no CONTAINS or COVERS relationships).

**test_ingest_suite_handles_multiple_feature_map_matches**
Build a suite with two test cases both present in feature_map.
Assert exactly two session.run calls contained "COVERS".

---

## Step 4: Create tests/test_graph_schema.py

This file tests app/graph/schema.py. Target lines: 27-36.

```python
from app.graph.schema import init_graph
```

### Tests to implement

**test_init_graph_calls_session_run_four_times**
Call init_graph with a mock driver.
Assert session.run was called exactly 4 times.

**test_init_graph_creates_testcase_constraint**
Capture all session.run call arguments.
Assert at least one call's argument contained "TestCase".

**test_init_graph_creates_feature_constraint**
Assert at least one session.run call argument contained "Feature".

**test_init_graph_creates_codemodule_constraint**
Assert at least one session.run call argument contained "CodeModule".

**test_init_graph_creates_bug_constraint**
Assert at least one session.run call argument contained "Bug".

**test_init_graph_uses_if_not_exists**
Assert every session.run call argument contained "IF NOT EXISTS".
This verifies constraints are idempotent and safe to run on every startup.

**test_init_graph_uses_create_constraint_syntax**
Assert every session.run call argument contained "CREATE CONSTRAINT".

---

## Step 5: Update pytest.ini

After all new tests pass and coverage reaches at least 80%, update pytest.ini:

Change:
  --cov-fail-under=79
To:
  --cov-fail-under=80

---

## Verification

Run:

```bash
pytest --ignore=tests/integration --ignore=tests/functional \
  --cov=app --cov-report=term-missing -v
```

All of the following must be true before this task is complete:
- All existing 85 tests still pass.
- All new tests pass.
- app/graph/queries.py coverage is above 70%.
- app/graph/seed.py coverage is above 70%.
- app/graph/ingest.py coverage is above 70%.
- app/graph/schema.py coverage is above 80%.
- Overall coverage is at or above 80%.
- pytest.ini --cov-fail-under is set to 80.

---

## Expected new and modified files

New files:
- tests/test_graph_queries.py
- tests/test_graph_seed.py
- tests/test_graph_ingest.py
- tests/test_graph_schema.py

Modified files:
- pytest.ini
