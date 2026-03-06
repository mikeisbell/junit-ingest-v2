# INSTRUCTIONS_AGENTIC.md

## Goal

Add a multi-step investigation agent that autonomously diagnoses a failing test suite and produces a structured diagnostic report. The agent receives a suite ID, executes a fixed investigation workflow across multiple steps, and returns a structured report with summary, root cause hypotheses, recurring patterns, and recommended next steps.

This is distinct from the POST /agent endpoint built in Layer 7. That endpoint lets Claude decide which tools to call. This endpoint runs a deterministic multi-step workflow where each step builds on the previous one.

---

## Constraints

- Do not modify parser.py, models.py, db_models.py, vector_store.py, rag.py, agent_tools.py, or agent.py.
- Do not change any existing endpoints.
- Do not remove the require_api_key dependency from any protected endpoint.
- Use claude-sonnet-4-6 as the model for all Claude API calls in this layer.
- The investigation workflow must execute all steps in sequence even if some steps return empty results. Never short-circuit the workflow based on intermediate results.
- The final report must be a structured dict, not free-form text. Claude generates the content but your code enforces the structure.
- Use the existing structured logging pattern from app/logging_config.py.

---

## Step 1: Create app/investigator.py

Create a new file at app/investigator.py.

This module runs the deterministic investigation workflow.

It must expose one function:

```python
def investigate_suite(suite_id: int, db: Session) -> dict
```

This function executes these steps in order:

**Step 1: Fetch suite details**
Call `execute_get_suite_by_id(inputs={"suite_id": suite_id}, db=db)` from app.agent_tools.
If the result contains an "error" key, return immediately with:
```python
{"error": f"Suite {suite_id} not found.", "suite_id": suite_id}
```
Log INFO with message "investigation_step" and extra fields `suite_id`, `step` set to "fetch_suite", and `status` set to "complete".

**Step 2: Search for similar historical failures**
For each failed or errored test case in the suite, call `execute_search_failures` from app.agent_tools with the failure message as the query and n_results=3.
Collect all results into a flat list, deduplicated by test_case_id.
Log INFO with message "investigation_step" and extra fields `suite_id`, `step` set to "search_similar", `failure_count` set to the number of failures searched, and `similar_count` set to the total similar results found.

**Step 3: Get failure stats**
Call `execute_get_failure_stats(inputs={"limit": 10}, db=db)` from app.agent_tools.
Log INFO with message "investigation_step" and extra fields `suite_id` and `step` set to "get_stats".

**Step 4: Generate structured report via Claude**
Build a prompt that includes all data gathered in Steps 1 through 3 and asks Claude to produce a structured JSON report.

Use this system prompt:
```
You are a test failure analyst. You will be given data about a failing test suite and asked to produce a structured diagnostic report. You must respond with valid JSON only. No markdown, no preamble, no explanation outside the JSON structure.
```

Build the user message including:
- The suite details from Step 1
- The similar historical failures from Step 2
- The failure stats from Step 3

Ask Claude to return a JSON object with exactly these keys:
- `summary`: a 2-3 sentence plain English summary of what failed and the likely impact
- `root_cause_hypotheses`: a list of dicts, each with keys `hypothesis` (string) and `confidence` (one of "high", "medium", "low")
- `recurring_patterns`: a list of dicts, each with keys `test_name` (string) and `failure_count` (int) for tests that appear in the stats with more than one failure
- `recommended_next_steps`: a list of strings, each a concrete actionable recommendation

Call the Anthropic API with model `claude-sonnet-4-6`, max_tokens 1024, and the system and user messages.

Parse the response text as JSON. If parsing fails, return a fallback structure with the raw text in a `raw_response` key and an `error` key explaining the parse failure.

Log INFO with message "investigation_step" and extra fields `suite_id` and `step` set to "generate_report".

**Step 5: Assemble and return the final report**
Return a dict with these keys:
- `suite_id`: int
- `suite_name`: str, from the suite details
- `total_tests`: int
- `total_failures`: int
- `total_errors`: int
- `similar_failures_found`: int, count of similar historical failures
- `report`: the structured dict from Step 4
- `steps_executed`: list of step names executed in order

---

## Step 2: Create app/investigator_tasks.py

Create a new file at app/investigator_tasks.py.

This module defines the Celery task for the investigation workflow.

```python
@celery_app.task(bind=True, max_retries=2, default_retry_delay=10)
def investigate_suite_task(self, suite_id: int) -> dict
```

This task:
1. Creates a database session using SessionLocal from app.database.
2. Calls `investigate_suite(suite_id=suite_id, db=db)` from app.investigator.
3. Closes the database session in a finally block.
4. Logs INFO with message "investigate_task_complete" and extra fields `suite_id` and `steps_executed`.
5. On exception, logs ERROR with message "investigate_task_failed" and extra fields `suite_id` and `error`. Retries up to 2 times.
6. Returns the dict from investigate_suite.

---

## Step 3: Update app/celery_app.py

Add `"app.investigator_tasks"` to the include list in the Celery app constructor.

The include list should now be:
```python
include=["app.tasks", "app.agent_tasks", "app.investigator_tasks"]
```

---

## Step 4: Add POST /investigate/{suite_id} endpoint to main.py

Add a new endpoint to main.py:

```
POST /investigate/{suite_id}
```

This endpoint requires Bearer token auth.

The suite_id is an integer path parameter.

The endpoint must:
1. Dispatch `investigate_suite_task.delay(suite_id=suite_id)` from app.investigator_tasks.
2. Log INFO with message "investigate_task_queued" and extra fields `suite_id` and `api_key_name`.
3. Return HTTP 202 with this response body:

```json
{
  "task_id": "the-celery-task-id",
  "status": "pending",
  "suite_id": 1
}
```

---

## Step 5: Add GET /investigate/result/{task_id} endpoint to main.py

Add a new endpoint to main.py:

```
GET /investigate/result/{task_id}
```

This endpoint requires Bearer token auth.

It must follow the same polling pattern as GET /analyze/{task_id} and GET /agent/{task_id}.

Return HTTP 200 in all cases with this structure depending on task state:

Pending or started:
```json
{
  "task_id": "abc-123",
  "status": "pending"
}
```

Success:
```json
{
  "task_id": "abc-123",
  "status": "complete",
  "suite_id": 1,
  "suite_name": "SampleTestSuite",
  "total_tests": 5,
  "total_failures": 1,
  "total_errors": 1,
  "similar_failures_found": 3,
  "report": {
    "summary": "...",
    "root_cause_hypotheses": [...],
    "recurring_patterns": [...],
    "recommended_next_steps": [...]
  },
  "steps_executed": ["fetch_suite", "search_similar", "get_stats", "generate_report"]
}
```

Failure:
```json
{
  "task_id": "abc-123",
  "status": "failed",
  "error": "the exception message"
}
```

---

## Step 6: Tests

Add a new test file at tests/test_investigator.py.

Write pytest tests that cover:

1. POST /investigate/{suite_id} with a valid Bearer token returns HTTP 202 with `task_id`, `status` equal to "pending", and `suite_id`. Mock `investigate_suite_task.delay`.

2. GET /investigate/result/{task_id} when task is pending returns HTTP 200 with status "pending". Mock `celery_app.AsyncResult`.

3. GET /investigate/result/{task_id} when task is complete returns HTTP 200 with status "complete" and keys `suite_id`, `suite_name`, `report`, and `steps_executed`. Mock `celery_app.AsyncResult` to return SUCCESS state with a realistic result dict.

4. GET /investigate/result/{task_id} when task failed returns HTTP 200 with status "failed". Mock `celery_app.AsyncResult` to return FAILURE state.

5. Test `investigate_suite` directly with a mock db session and mocked agent_tools functions. Assert that all four steps execute and the returned dict contains `suite_id`, `report`, and `steps_executed` with all four step names.

6. Test `investigate_suite` when the suite is not found. Mock `execute_get_suite_by_id` to return `{"error": "Suite 999 not found."}`. Assert the function returns immediately with an error key and does not call any other tools.

Use unittest.mock.patch for all mocks. Do not make real API calls or database queries in tests.

---

## Expected file changes summary

- app/investigator.py: new file
- app/investigator_tasks.py: new file
- app/celery_app.py: add investigator_tasks to include list
- app/main.py: add POST /investigate/{suite_id} and GET /investigate/result/{task_id} endpoints
- tests/test_investigator.py: new test file
