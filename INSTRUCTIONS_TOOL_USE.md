# INSTRUCTIONS_TOOL_USE.md

## Goal

Add a POST /agent endpoint that gives Claude four tools to call against your data. Claude decides which tools to call and in what order based on the query. The endpoint runs a tool use loop: call Claude, execute any requested tools, feed results back to Claude, repeat until Claude produces a final text response.

---

## Constraints

- Do not modify parser.py, models.py, db_models.py, vector_store.py, or rag.py.
- Do not change any existing endpoints.
- Do not remove the require_api_key dependency from any protected endpoint.
- Use the anthropic Python SDK tool use API. Do not implement tool use manually.
- Use claude-sonnet-4-5-20250514 as the model for the agent endpoint. Tool use requires a more capable model than Haiku.
- The tool use loop must have a maximum of 10 iterations to prevent infinite loops.
- All tool execution must be synchronous inside the Celery task. Do not create nested async tasks.
- Use the existing structured logging pattern from app/logging_config.py.

---

## Step 1: Create app/agent_tools.py

Create a new file at app/agent_tools.py.

This module defines the four tools Claude can call and the functions that execute them.

**Tool definitions**

Define a list named `TOOL_DEFINITIONS` containing four tool definition dicts in the Anthropic tool use format. Each dict has keys `name`, `description`, and `input_schema`.

Tool 1: `search_failures`
- Description: "Search for test failures semantically similar to a query string. Use this when the user asks about specific kinds of failures or error messages."
- Input schema: `query` (string, required), `n_results` (integer, optional, default 5)

Tool 2: `get_suite_by_id`
- Description: "Fetch a specific test suite result by its integer ID. Use this when the user references a specific suite ID or wants details about a particular test run."
- Input schema: `suite_id` (integer, required)

Tool 3: `get_recent_failures`
- Description: "Fetch the most recent failed test cases across all suites. Use this when the user asks about recent failures or wants to see what has been failing lately."
- Input schema: `limit` (integer, optional, default 10, maximum 50)

Tool 4: `get_failure_stats`
- Description: "Count how many times each test case has failed across all suites. Use this when the user asks about recurring failures, flaky tests, or which tests fail most often."
- Input schema: `limit` (integer, optional, default 10, maximum 50)

**Tool executor functions**

Define four functions that execute each tool. Each function takes a dict of tool inputs and a SQLAlchemy Session, and returns a dict.

Function 1: `execute_search_failures(inputs: dict) -> dict`
- Calls `search_failures(query=inputs["query"], n_results=inputs.get("n_results", 5))` from app.vector_store.
- Returns `{"results": the list of result dicts}`.
- If the results list is empty, returns `{"results": [], "message": "No similar failures found."}`.

Function 2: `execute_get_suite_by_id(inputs: dict, db: Session) -> dict`
- Queries Postgres for a TestSuiteResultORM record by ID.
- If not found, returns `{"error": "Suite {id} not found."}`.
- If found, returns a dict with keys: `id`, `name`, `total_tests`, `total_failures`, `total_errors`, `total_skipped`, `elapsed_time`, and `test_cases` (a list of dicts with keys `name`, `status`, `failure_message`).

Function 3: `execute_get_recent_failures(inputs: dict, db: Session) -> dict`
- Queries Postgres for TestCaseORM records where status is "failed" or "error", ordered by id descending, limited to `inputs.get("limit", 10)`.
- Returns `{"failures": list of dicts with keys `test_case_id`, `suite_id`, `name`, `status`, `failure_message`}`.

Function 4: `execute_get_failure_stats(inputs: dict, db: Session) -> dict`
- Queries Postgres for TestCaseORM records where status is "failed" or "error".
- Groups by test case name and counts occurrences.
- Returns the top N by count where N is `inputs.get("limit", 10)`.
- Returns `{"stats": list of dicts with keys `name`, `failure_count`}` sorted by failure_count descending.

**Tool dispatch function**

Define a function named `execute_tool(tool_name: str, tool_inputs: dict, db: Session) -> dict` that dispatches to the correct executor function based on tool_name. If tool_name is not recognized, return `{"error": "Unknown tool: {tool_name}"}`.

---

## Step 2: Create app/agent.py

Create a new file at app/agent.py.

This module runs the tool use loop.

It must expose one function:

```python
def run_agent(query: str, db: Session) -> dict
```

This function:

1. Initializes the conversation with a system prompt and the user query. Use this system prompt:

```
You are a test failure analyst with access to a test results database. 
Use the available tools to gather relevant data before answering. 
Always use at least one tool before providing your final answer.
Base your analysis only on data returned by the tools.
Be concise and specific in your analysis.
```

2. Calls the Anthropic API with the user message, the system prompt, `TOOL_DEFINITIONS` from agent_tools.py, and `max_tokens=2048`.

3. Runs a loop with a maximum of 10 iterations:
   - If the response `stop_reason` is `"end_turn"`, extract the final text response and break.
   - If the response `stop_reason` is `"tool_use"`, find all content blocks with type `"tool_use"`.
   - For each tool use block, call `execute_tool(tool_name, tool_inputs, db)` from agent_tools.py.
   - Log INFO with message `"tool_called"` and extra fields `tool_name` and `tool_use_id`.
   - Build a tool result message in the Anthropic format and append it to the conversation history.
   - Call the Anthropic API again with the updated conversation history.
   - If the loop reaches 10 iterations without an end_turn, return the last text response found or a fallback message.

4. Return a dict with these keys:
   - `query`: the original query string
   - `answer`: the final text response from Claude
   - `tools_called`: a list of tool names that were called during the loop, in order
   - `iterations`: the number of loop iterations executed

---

## Step 3: Create app/agent_tasks.py

Create a new file at app/agent_tasks.py.

This module defines the Celery task for the agent.

```python
@celery_app.task(bind=True, max_retries=2, default_retry_delay=10)
def run_agent_task(self, query: str) -> dict
```

This task:
1. Creates a database session using SessionLocal from app.database.
2. Calls `run_agent(query=query, db=db)` from app.agent.
3. Closes the database session in a finally block.
4. Logs INFO with message `"agent_task_complete"` and extra fields `query`, `tools_called`, and `iterations`.
5. On exception, logs ERROR with message `"agent_task_failed"` and extra fields `query` and `error`. Retries up to 2 times.
6. Returns the dict from run_agent.

---

## Step 4: Update app/celery_app.py

Add `"app.agent_tasks"` to the `include` list in the Celery app constructor so the worker registers the new task.

The include list should now be:
```python
include=["app.tasks", "app.agent_tasks"]
```

---

## Step 5: Add POST /agent endpoint to main.py

Add a new endpoint to main.py:

```
POST /agent
```

This endpoint requires Bearer token auth.

Request body:
```json
{
  "query": "which tests are failing most often?",
  "n": 5
}
```

The `query` field is required. The `n` field is optional and not used directly by the agent but included for interface consistency.

The endpoint must:
1. Validate that query is not empty or whitespace. Return HTTP 400 with message "query is required" if it is.
2. Dispatch `run_agent_task.delay(query=query)` from app.agent_tasks.
3. Log INFO with message `"agent_task_queued"` and extra field `query`.
4. Return HTTP 202 with this response body:

```json
{
  "task_id": "the-celery-task-id",
  "status": "pending"
}
```

---

## Step 6: Add GET /agent/{task_id} endpoint to main.py

Add a new endpoint to main.py:

```
GET /agent/{task_id}
```

This endpoint requires Bearer token auth.

It must follow the same polling pattern as GET /analyze/{task_id}.

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
  "query": "which tests are failing most often?",
  "answer": "Based on the data...",
  "tools_called": ["get_failure_stats", "search_failures"],
  "iterations": 2
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

## Step 7: Tests

Add a new test file at tests/test_agent.py.

Write pytest tests that cover:

1. POST /agent with a valid Bearer token returns HTTP 202 with `task_id` and `status` equal to `"pending"`. Mock `run_agent_task.delay`.

2. POST /agent with an empty query returns HTTP 400.

3. GET /agent/{task_id} when task is pending returns HTTP 200 with status `"pending"`. Mock `celery_app.AsyncResult`.

4. GET /agent/{task_id} when task is complete returns HTTP 200 with status `"complete"` and keys `answer`, `tools_called`, and `iterations`. Mock `celery_app.AsyncResult` to return a SUCCESS state with a realistic result dict.

5. GET /agent/{task_id} when task failed returns HTTP 200 with status `"failed"`. Mock `celery_app.AsyncResult` to return FAILURE state.

6. Test `execute_tool` dispatch in agent_tools.py: call it with tool_name `"get_failure_stats"` and a mock db session. Assert it returns a dict with a `"stats"` key.

7. Test `execute_tool` with an unknown tool name. Assert it returns a dict with an `"error"` key.

Use unittest.mock.patch for all mocks. Do not make real API calls or database queries in tests.

---

## Expected file changes summary

- app/agent_tools.py: new file
- app/agent.py: new file
- app/agent_tasks.py: new file
- app/celery_app.py: add agent_tasks to include list
- app/main.py: add POST /agent and GET /agent/{task_id} endpoints
- tests/test_agent.py: new test file
