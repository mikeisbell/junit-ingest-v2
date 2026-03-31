# INSTRUCTIONS_LAYER12_BUGFIXES.md

## Overview

Fix three known bugs in the Layer 12 knowledge graph and CI webhook integration.
Each fix is described with its root cause and the exact change required.
Do not modify any file not listed in this document.

---

## Bug 1: graph_context returns feature_count=0 for demo.xml

### Root cause

The `graph_context` step in `investigate_suite()` traverses
`(TestCase)-[:COVERS]->(Feature)` relationships in Neo4j. Those relationships
are created by `ingest_suite_to_graph()`. However, the demo flow in
`demo/ingest.py` posts the XML to the API to persist the suite to Postgres but
does not call `ingest_suite_to_graph()` to write the suite into Neo4j.
As a result, no `TestCase` nodes or `COVERS` relationships exist in the graph
when the investigator runs, so `feature_count` is always 0.

### Fix

Open `demo/ingest.py`. After the successful POST to `/results`, add a call to
`ingest_suite_to_graph()` using the Neo4j driver and the parsed suite result.

The demo script already imports or has access to the feature map. Load
`demo/data/feature_map.json` and pass it to `ingest_suite_to_graph()` along
with the driver and the parsed `TestSuiteResult` object.

The driver should be obtained by calling `get_driver()` from `app.graph.driver`.
If the driver is None (Neo4j not running), log a warning and continue without
raising.

The ingest call must happen after the suite is successfully parsed and before
the webhook call or at the same point in the script where results are available.

Import additions needed in demo/ingest.py:
- `from app.graph.driver import get_driver`
- `from app.graph.ingest import ingest_suite_to_graph`
- `import json` (if not already present)

Logic to add after parsing the suite result:
```python
driver = get_driver()
if driver:
    feature_map_path = Path(__file__).parent / "data" / "feature_map.json"
    with open(feature_map_path) as f:
        feature_map = json.load(f)
    ingest_suite_to_graph(driver, suite_result, feature_map)
    driver.close()
else:
    print("Neo4j unavailable, skipping graph ingest")
```

Adjust variable names to match what already exists in demo/ingest.py.

---

## Bug 2: Neo4j warning "Expected single record, found multiple" in get_gap_analysis

### Root cause

In `app/graph/queries.py`, `get_gap_analysis()` runs this query and calls
`.single()` on the result:

```cypher
MATCH (b:Bug {id: $bug_id})-[:AFFECTS]->(f:Feature)
OPTIONAL MATCH (t:TestCase)-[:COVERS]->(f)
RETURN f.name AS feature_name,
       f.description AS feature_description,
       collect({name: t.name, suite_name: t.suite_name, status: t.status}) AS tests
```

When a Bug affects more than one Feature (BUG-001 affects both `shopping_cart`
and `checkout_flow`), this query returns multiple rows — one per feature.
Calling `.single()` on multiple rows triggers the Neo4j warning and returns
only the first row, silently discarding coverage data for the other features.

### Fix

Restructure the query to aggregate features into a list so the query always
returns exactly one row regardless of how many features a bug affects.

Replace the coverage query in `get_gap_analysis()` with:

```cypher
MATCH (b:Bug {id: $bug_id})-[:AFFECTS]->(f:Feature)
OPTIONAL MATCH (t:TestCase)-[:COVERS]->(f)
WITH f, collect({name: t.name, suite_name: t.suite_name, status: t.status}) AS tests
RETURN collect({
    feature_name: f.name,
    feature_description: f.description,
    tests: tests
}) AS features
```

After this change the coverage_record will have a single `features` key
containing a list of feature dicts, each with their own tests list.

Update the code that processes `coverage_record` to:
1. Read `coverage_record["features"]` instead of individual fields.
2. Flatten all tests across all features into a single `covering_tests` list,
   filtering out null entries as before.
3. Update the `affected_feature` field in the return dict to be a list of
   feature dicts instead of a single dict, since a bug can affect multiple
   features. Each item should have keys `name` and `description`.
4. Keep the `gap_assessment` logic identical: it operates on the combined
   `covering_tests` list across all features.

The updated return structure for a successful response should be:
```json
{
  "bug": {"id": "...", "title": "...", "severity": "...", "escaped": true},
  "affected_features": [
    {"name": "shopping_cart", "description": "..."},
    {"name": "checkout_flow", "description": "..."}
  ],
  "covering_tests": [...],
  "gap_assessment": "covered"
}
```

Note the key name change from `affected_feature` (singular) to
`affected_features` (plural). Update the return dict key accordingly.

After making this change, update `tests/test_graph_queries.py` to reflect the
new return structure:
- Tests that assert on `affected_feature` key must be updated to `affected_features`.
- Tests that assert `affected_features` is a dict must be updated to assert it
  is a list.
- Add one new test: `test_get_gap_analysis_returns_list_of_affected_features`
  that asserts `affected_features` is a list with at least one item when a
  valid bug with one affected feature is returned.

---

## Bug 3: DevRev issue body is empty (Summary, Hypotheses, Steps all blank)

### Root cause

In `ci_webhook.py`, `investigate_suite(db_suite.id, db, driver=driver)` is
called after `db.commit()` and `db.refresh(db_suite)`. However `db.refresh()`
only reloads scalar columns on the ORM object. It does not eagerly load the
`test_cases` relationship. When `execute_get_suite_by_id()` inside
`investigate_suite()` queries for the suite's test cases, SQLAlchemy may not
load them within the same session context, resulting in an empty test cases list
being passed to Claude. With no failure messages, Claude produces empty
`summary`, `root_cause_hypotheses`, and `recommended_next_steps` fields.

### Fix

In `ci_webhook.py`, after `db.refresh(db_suite)`, explicitly load the
`test_cases` relationship before calling `investigate_suite()`.

Add this line immediately after `db.refresh(db_suite)`:

```python
_ = db_suite.test_cases  # eagerly load relationship within this session
```

This forces SQLAlchemy to issue the SELECT for test cases while the session is
still open and the suite ID is valid, so `execute_get_suite_by_id()` can
retrieve them correctly.

If that does not resolve the issue, check `app/agent_tools.py` in the
`execute_get_suite_by_id()` function. That function queries Postgres for the
suite and its test cases. Verify that it uses `joinedload` or accesses
`suite.test_cases` within the session scope. If it opens its own session
using a dependency rather than receiving the db session as a parameter, confirm
the suite ID is committed and visible to a new session before the call.

---

## Verification

After all three fixes are applied:

1. Restart Docker: `docker compose down && docker compose up --build -d`

2. Run the demo seed: `docker compose exec api python demo/seed.py`

3. Run the demo ingest: `docker compose exec api python demo/ingest.py`

4. Check the investigate response for `feature_count > 0` in the logs:
   `docker compose logs api | grep graph_context`

5. Check that no Neo4j warning appears:
   `docker compose logs api | grep "Expected single record"`

6. POST demo.xml to the webhook endpoint and verify the DevRev issue body
   contains non-empty Summary, Hypotheses, and Next Steps sections.

7. Run the full test suite to confirm no regressions:
   ```bash
   pytest --ignore=tests/integration --ignore=tests/functional \
     --cov=app --cov-report=term-missing -v
   ```
   All tests must pass and coverage must remain at or above 80%.

---

## Files to modify

- `demo/ingest.py` (Bug 1)
- `app/graph/queries.py` (Bug 2)
- `tests/test_graph_queries.py` (Bug 2 test updates)
- `app/ci_webhook.py` (Bug 3)

Do not modify any other files.
