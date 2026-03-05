# INSTRUCTIONS_RAG.md

## Goal

Extend the JUnit XML ingestion service with a RAG endpoint. When a caller sends a natural language query, the service retrieves the most similar failure messages from ChromaDB, passes them as context to the Anthropic Claude API, and returns a model-generated analysis grounded in those failures.

Also add a small evaluation harness that measures retrieval quality against a known set of queries and expected results.

---

## Constraints

- Do not modify parser.py, models.py, db_models.py, or vector_store.py.
- Do not change any existing endpoints.
- Use the anthropic Python SDK for all Claude API calls.
- Use claude-haiku-3-5-20241022 as the model. It is fast and cheap for this use case.
- Read the Anthropic API key from an environment variable named ANTHROPIC_API_KEY. Never hardcode it.
- Keep the RAG logic in a dedicated module. Do not put it in main.py directly.

---

## Step 1: Add anthropic to requirements

Add `anthropic` to requirements.txt. Do not pin a specific version.

---

## Step 2: Add ANTHROPIC_API_KEY to docker-compose.yml

In the api service environment block, add:

```
- ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
```

This passes the key from the host environment into the container. Do not hardcode a value.

---

## Step 3: Create app/rag.py

Create a new file at app/rag.py.

This module handles prompt construction and Claude API calls.

It must expose one function:

```python
def analyze_failures(query: str, failures: list[dict]) -> str
```

The `failures` parameter is a list of dicts as returned by `search_failures` in vector_store.py. Each dict has keys: `test_case_id`, `suite_id`, `name`, `failure_message`, and `distance`.

This function must:

1. Build a prompt that includes the query and the retrieved failures as context. Structure the prompt like this:

```
You are a test failure analyst. A user has asked the following question about test failures:

"{query}"

Here are the most relevant test failures retrieved from the test results database:

{for each failure, formatted as:}
Test: {name}
Failure: {failure_message}

Based only on the failures above, provide a concise analysis that answers the user's question. If the failures do not contain enough information to answer the question, say so clearly.
```

2. Call the Anthropic API using the anthropic Python SDK. Use the `anthropic.Anthropic()` client. Read the API key from the environment variable ANTHROPIC_API_KEY automatically via the SDK default behavior (the SDK reads it from the environment if not passed explicitly).

3. Use model `claude-haiku-3-5-20241022`, max_tokens 512.

4. Return the text content of the first content block in the response.

5. If the failures list is empty, do not call the API. Return the string "No relevant failures found for this query." instead.

6. If the API call raises an exception, re-raise it. Do not silently swallow errors here. The endpoint handler will catch it.

---

## Step 4: Add POST /analyze endpoint

Add a new endpoint to main.py:

```
POST /analyze
```

This endpoint accepts a JSON request body with this structure:

```json
{
  "query": "why are my login tests failing?",
  "n": 5
}
```

The `query` field is required. The `n` field is optional, default 5, minimum 1, maximum 20.

The endpoint must:

1. Validate that query is not empty or whitespace only. Return HTTP 400 with message "query is required" if it is.

2. Call `search_failures(query=query, n_results=n)` from app.vector_store.

3. Call `analyze_failures(query=query, failures=results)` from app.rag.

4. Return a JSON response with this structure:

```json
{
  "query": "why are my login tests failing?",
  "failures_used": 3,
  "analysis": "Based on the retrieved failures, the login tests are failing due to..."
}
```

Where `failures_used` is the count of failures passed to the model.

5. If `analyze_failures` raises an exception, return HTTP 502 with message "Analysis service unavailable."

---

## Step 5: Create tests/eval/eval_retrieval.py

Create a new file at tests/eval/eval_retrieval.py.

This is a standalone evaluation script, not a pytest test. It runs against the live service.

It must:

1. Define a list of eval cases. Each eval case is a dict with these keys:
   - `query`: a natural language string
   - `expected_keywords`: a list of strings that should appear in at least one returned failure message

Use these eval cases as the starting set:

```python
EVAL_CASES = [
    {
        "query": "assertion errors where expected value did not match actual",
        "expected_keywords": ["AssertionError", "Expected", "assert"]
    },
    {
        "query": "null pointer or attribute errors",
        "expected_keywords": ["NullPointer", "AttributeError", "null", "None"]
    },
    {
        "query": "timeout or connection failures",
        "expected_keywords": ["timeout", "Timeout", "connection", "Connection"]
    }
]
```

2. For each eval case, call GET /search on the running service with the query and n=5.

3. Check whether any of the expected_keywords appear in any of the returned failure messages. The check is case-insensitive.

4. Print a result for each eval case in this format:

```
PASS [assertion errors where expected value did not match actual] — 3/5 results matched keywords
FAIL [null pointer or attribute errors] — 0/5 results matched keywords
```

5. Print a final summary line:

```
Retrieval eval complete: 2/3 passed
```

6. Read the base URL from an environment variable SERVICE_URL with default `http://localhost:8001`.

7. Use the `requests` library for HTTP calls.

This script is intentionally simple. It is not a pytest test. It is meant to be run manually after the Docker stack is up and test data has been ingested.

---

## Step 6: Create tests/eval/README.md

Create a new file at tests/eval/README.md with these contents:

```markdown
# Retrieval Evaluation

This directory contains the retrieval evaluation harness for the JUnit XML ingestion service.

## What it does

eval_retrieval.py runs a set of natural language queries against the live GET /search endpoint and checks whether the returned failure messages contain expected keywords. It measures whether semantic search is returning relevant results.

## How to run

1. Start the Docker stack: `docker compose up --build`
2. Ingest at least one JUnit XML file with failures via POST /results
3. Run the eval: `python tests/eval/eval_retrieval.py`

## Adding eval cases

Add new dicts to the EVAL_CASES list in eval_retrieval.py. Each case needs a query string and a list of expected_keywords to match against returned failure messages.
```

---

## Step 7: Tests

Add a new test file at tests/test_rag.py.

Write pytest tests that cover:

1. POST /analyze with a valid query after failures have been ingested. Mock both `search_failures` and `analyze_failures`. Assert the response is HTTP 200 and contains the keys `query`, `failures_used`, and `analysis`.

2. POST /analyze with an empty query string. Assert the response is HTTP 400.

3. POST /analyze when `analyze_failures` raises an exception. Mock it to raise. Assert the response is HTTP 502.

4. POST /analyze when no failures exist. Mock `search_failures` to return an empty list and `analyze_failures` to return "No relevant failures found for this query." Assert the response is HTTP 200 and `failures_used` is 0.

Use unittest.mock.patch for all mocks. Do not make real API calls in tests.

---

## Expected file changes summary

- requirements.txt: add anthropic
- docker-compose.yml: add ANTHROPIC_API_KEY to api service environment
- app/rag.py: new file
- app/main.py: add POST /analyze endpoint
- tests/test_rag.py: new test file
- tests/eval/eval_retrieval.py: new eval script
- tests/eval/README.md: new readme
