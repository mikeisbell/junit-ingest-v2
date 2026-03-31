# INSTRUCTIONS_FUNCTIONAL_TESTS.md

## Goal

Add a functional test suite that verifies AI system behavior at two levels: structural tests that use mocked Claude API responses to verify response shapes and infrastructure behavior, and behavioral tests that make real Claude API calls and real ChromaDB queries to verify that the AI system does what it claims to do.

---

## Constraints

- Do not modify any existing application code.
- Do not modify any existing test files.
- Structural tests must run without a live Docker stack and without real API calls.
- Behavioral tests require a live Docker stack and a valid ANTHROPIC_API_KEY. They are marked with a custom pytest marker so they can be run separately.
- Behavioral tests must be idempotent. Each test ingests its own known data and cleans up after itself or uses isolated query strings unlikely to collide with other test data.
- All functional tests live in tests/functional/.
- Use pytest for all tests, both structural and behavioral.
- Register a custom pytest marker named `behavioral` in pytest.ini so pytest does not warn about unknown markers.

---

## Step 1: Update pytest.ini

Add or update pytest.ini in the project root to register the behavioral marker and exclude the functional directory from the default test run:

```ini
[pytest]
testpaths = tests
ignore = tests/integration tests/functional
markers =
    behavioral: marks tests as behavioral tests requiring live stack and real API calls (deselect with '-m "not behavioral"')
```

This ensures `pytest tests/` continues to run only unit tests. Functional tests are run explicitly with `pytest tests/functional/`.

---

## Step 2: Create tests/functional/__init__.py

Create an empty file at tests/functional/__init__.py.

---

## Step 3: Create tests/functional/conftest.py

Create a new file at tests/functional/conftest.py.

This file provides shared fixtures for all functional tests.

It must:

1. Define a fixture named `service_url` that reads SERVICE_URL from the environment with default `http://localhost:8001`.

2. Define a fixture named `api_key` that reads API_KEY from the environment. If not set, skip the test with the message "API_KEY environment variable not set".

3. Define a fixture named `auth_headers` that returns a dict with the Authorization Bearer header using the api_key fixture.

4. Define a fixture named `ingested_suite` that:
   - Ingests the rich sample XML file at tests/sample_rich.xml via POST /results using the auth_headers fixture.
   - Returns the parsed response dict.
   - This fixture has session scope so ingestion happens once per test session.

5. Define a fixture named `known_failure_xml` that returns a minimal JUnit XML string with a single known failure message: "ZeroDivisionError: division by zero in calculate_discount function". This is used by behavioral tests that need predictable failure content.

---

## Step 4: Create tests/functional/test_structural.py

Create a new file at tests/functional/test_structural.py.

These tests use mocked Claude API calls and verify response structure. They do not require a live Docker stack.

Write these structural tests:

**Test 1: investigate report structure**
Mock `app.investigator.anthropic.Anthropic` to return a response with a valid JSON report string containing all four required keys: `summary`, `root_cause_hypotheses`, `recurring_patterns`, `recommended_next_steps`.
Call `investigate_suite(suite_id=1, db=mock_db)` directly.
Assert the returned dict contains keys `suite_id`, `report`, and `steps_executed`.
Assert `steps_executed` contains all four step names: "fetch_suite", "search_similar", "get_stats", "generate_report".
Assert `report` contains all four required keys.

**Test 2: investigate early exit on missing suite**
Mock `execute_get_suite_by_id` to return `{"error": "Suite 999 not found."}`.
Call `investigate_suite(suite_id=999, db=mock_db)`.
Assert the returned dict contains an `error` key.
Assert `execute_get_failure_stats` was never called.

**Test 3: analyze failures returns structure**
Mock the Anthropic client in rag.py to return a response with analysis text "Test analysis response."
Call `analyze_failures(query="test query", failures=[{"test_case_id": 1, "suite_id": 1, "name": "test_fail", "failure_message": "AssertionError", "distance": 0.5}])` directly.
Assert the return value is a non-empty string.

**Test 4: analyze failures with empty list skips API call**
Call `analyze_failures(query="test query", failures=[])` directly without mocking.
Assert the return value equals "No relevant failures found for this query."
Assert no Anthropic API call was made.

**Test 5: agent returns structure with mocked tools and API**
Mock all four tool executor functions in agent_tools.py to return empty result dicts.
Mock the Anthropic client in agent.py to return a response with stop_reason "end_turn" and text content "Mocked agent response."
Call `run_agent(query="test query", db=mock_db)` directly.
Assert the returned dict contains keys `query`, `answer`, `tools_called`, and `iterations`.
Assert `answer` equals "Mocked agent response."

**Test 6: rate limit returns 429 after limit exceeded**
Mock `check_rate_limit` to return `(False, 0)`.
Use TestClient to call GET /search with a valid auth header.
Assert response status is 429.
Assert response body contains "Rate limit exceeded".

**Test 7: cache hit skips vector store call**
Mock `get_cached` to return a pre-built search result dict.
Mock `search_failures` in vector_store.
Use TestClient to call GET /search.
Assert response status is 200.
Assert `search_failures` was never called.

**Test 8: cache miss calls vector store and sets cache**
Mock `get_cached` to return None.
Mock `search_failures` to return an empty list.
Mock `set_cached`.
Use TestClient to call GET /search.
Assert `search_failures` was called once.
Assert `set_cached` was called once.

---

## Step 5: Create tests/functional/test_behavioral.py

Create a new file at tests/functional/test_behavioral.py.

These tests make real Claude API calls and real ChromaDB queries. They are marked with `@pytest.mark.behavioral` and require a live Docker stack.

All tests in this file must use the `service_url`, `auth_headers`, and `ingested_suite` fixtures from conftest.py.

Write these behavioral tests:

**Test 1: semantic search returns relevant results for assertion error query**
Mark with `@pytest.mark.behavioral`.
Requires `ingested_suite` fixture to ensure data is present.
Call GET /search with query "AssertionError expected value did not match" and n=5.
Assert response status is 200.
Assert results list is non-empty.
Assert at least one result has a failure_message containing "AssertionError" or "assert" (case-insensitive).
Assert all results have a distance field that is a float.

**Test 2: semantic search returns relevant results for connection error query**
Mark with `@pytest.mark.behavioral`.
Call GET /search with query "connection refused timeout failed to connect" and n=5.
Assert response status is 200.
Assert at least one result has a failure_message containing "connection" or "timeout" (case-insensitive).

**Test 3: semantic search returns relevant results for null pointer query**
Mark with `@pytest.mark.behavioral`.
Call GET /search with query "NullPointerException AttributeError NoneType object" and n=5.
Assert response status is 200.
Assert at least one result has a failure_message containing "None" or "Null" or "Attribute" (case-insensitive).

**Test 4: analyze produces coherent response for known failure**
Mark with `@pytest.mark.behavioral`.
First ingest the known_failure_xml fixture via POST /results.
Submit POST /analyze with query "why is the discount calculation failing?" and n=3.
Assert response status is 202 and contains a task_id.
Poll GET /analyze/{task_id} up to 60 seconds every 3 seconds until status is "complete" or "failed".
Assert final status is "complete".
Assert the analysis field is a non-empty string with more than 20 characters.
Assert failures_used is an integer greater than or equal to 0.

**Test 5: agent calls at least one tool for failure stats query**
Mark with `@pytest.mark.behavioral`.
Submit POST /agent with query "which tests have failed most often across all suites?".
Assert response status is 202 and contains a task_id.
Poll GET /agent/{task_id} up to 60 seconds every 3 seconds until status is "complete" or "failed".
Assert final status is "complete".
Assert tools_called is a non-empty list.
Assert "get_failure_stats" is in tools_called.
Assert answer is a non-empty string.

**Test 6: investigate produces structured report for known suite**
Mark with `@pytest.mark.behavioral`.
Requires `ingested_suite` fixture.
Use suite_id 1 (assumes at least one suite has been ingested).
Submit POST /investigate/1.
Assert response status is 202 and contains a task_id.
Poll GET /investigate/result/{task_id} up to 90 seconds every 3 seconds until status is "complete" or "failed".
Assert final status is "complete".
Assert report contains keys summary, root_cause_hypotheses, recommended_next_steps.
Assert summary is a non-empty string.
Assert recommended_next_steps is a non-empty list.
Assert steps_executed contains all four step names.

---

## Step 6: Create tests/functional/README.md

Create a new file at tests/functional/README.md with these contents:

```markdown
# Functional Tests

This directory contains functional tests that verify AI system behavior at two levels.

## Structural tests (test_structural.py)

Verify response shapes and infrastructure behavior using mocked Claude API calls.
Run without a live Docker stack.

```bash
pytest tests/functional/test_structural.py -v
```

## Behavioral tests (test_behavioral.py)

Verify that the AI system does what it claims to do using real Claude API calls and real ChromaDB queries.
Require a live Docker stack and valid environment variables.

### Setup

1. Start the Docker stack: `docker compose up --build -d --wait`
2. Issue an API key: `curl -X POST http://localhost:8001/keys -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" -d '{"name": "functional"}'`
3. Export the key: `export API_KEY=your-key-here`

### Run

```bash
pytest tests/functional/test_behavioral.py -v -m behavioral
```

### Cost

Each behavioral test run makes approximately 3 to 5 Claude API calls using claude-sonnet-4-6 and claude-haiku-4-5-20251001. Estimated cost per full run is under $0.05.

## Run all functional tests

```bash
pytest tests/functional/ -v
```
```

---

## Expected file changes summary

- pytest.ini: add behavioral marker registration and exclude functional directory from default run
- tests/functional/__init__.py: new empty file
- tests/functional/conftest.py: new file with shared fixtures
- tests/functional/test_structural.py: new file with 8 structural tests
- tests/functional/test_behavioral.py: new file with 6 behavioral tests
- tests/functional/README.md: new file
