# INSTRUCTIONS_OPTIMIZATION.md

## Goal

Add four production optimization features to the JUnit XML ingestion service: latency instrumentation on all endpoints, token cost tracking on all Claude API calls, Redis caching for search and analyze results, and rate limiting per API key using Redis.

---

## Constraints

- Do not modify parser.py, models.py, db_models.py, vector_store.py, or agent_tools.py.
- Do not change any existing endpoint response shapes.
- Do not remove the require_api_key dependency from any protected endpoint.
- Rate limit applies to all protected endpoints except GET /health.
- Cache applies only to GET /search and the synchronous analyze path. Do not cache agent or investigate results.
- Use the existing Redis client pattern already in the codebase. Read REDIS_URL from the environment.
- Use the existing structured logging pattern from app/logging_config.py.
- Rate limit is 30 requests per minute per API key.
- Cache TTL is 600 seconds (10 minutes).

---

## Step 1: Add latency instrumentation to middleware

In app/middleware.py, update the TraceIDMiddleware dispatch method to measure and log request latency.

After calling `call_next(request)` and before returning the response:
1. Calculate elapsed time in milliseconds from when the request was received.
2. Add the elapsed time as a response header `X-Response-Time-Ms`.
3. Log INFO with message "request_complete" and extra fields:
   - `method`: the HTTP method
   - `path`: the request path
   - `status_code`: the response status code
   - `duration_ms`: the elapsed time rounded to 2 decimal places
   - `trace_id`: already available via trace_id_var

Do not log requests to GET /health to avoid noise.

---

## Step 2: Add token cost tracking to rag.py

In app/rag.py, after a successful Claude API call in the `analyze_failures` function:

1. Read the token usage from the response: `response.usage.input_tokens` and `response.usage.output_tokens`.
2. Calculate estimated cost in USD using these rates:
   - Input: $3.00 per million tokens
   - Output: $15.00 per million tokens
3. Log INFO with message "claude_api_call" and extra fields:
   - `model`: the model string used
   - `input_tokens`: int
   - `output_tokens`: int
   - `estimated_cost_usd`: float rounded to 6 decimal places
   - `caller`: "analyze_failures"

---

## Step 3: Add token cost tracking to agent.py

In app/agent.py, after each Claude API call inside the tool use loop in `run_agent`:

1. Read token usage from the response the same way as Step 2.
2. Accumulate total input and output tokens across all iterations.
3. After the loop completes, log INFO with message "claude_api_call" and extra fields:
   - `model`: the model string used
   - `input_tokens`: total accumulated input tokens
   - `output_tokens`: total accumulated output tokens
   - `estimated_cost_usd`: float rounded to 6 decimal places
   - `caller`: "run_agent"
   - `iterations`: number of loop iterations

---

## Step 4: Add token cost tracking to investigator.py

In app/investigator.py, after the Claude API call in Step 4 of `investigate_suite`:

1. Read token usage from the response.
2. Log INFO with message "claude_api_call" and extra fields:
   - `model`: the model string used
   - `input_tokens`: int
   - `output_tokens`: int
   - `estimated_cost_usd`: float rounded to 6 decimal places
   - `caller`: "investigate_suite"

---

## Step 5: Create app/cache.py

Create a new file at app/cache.py.

This module handles Redis caching for search and analyze results.

It must:

1. Create a Redis client using `redis.from_url(REDIS_URL)` where REDIS_URL is read from the environment with default `redis://redis:6379/0`.

2. Expose a function named `get_cached`:

```python
def get_cached(key: str) -> dict | None
```

Returns the cached value as a parsed dict if the key exists, or None if not.

3. Expose a function named `set_cached`:

```python
def set_cached(key: str, value: dict, ttl_seconds: int = 600) -> None
```

Serializes the value as JSON and stores it with the given TTL.

4. Expose a function named `make_search_cache_key`:

```python
def make_search_cache_key(query: str, n_results: int) -> str
```

Returns a cache key string in the format `search:{hash}` where hash is the MD5 hex digest of `f"{query}:{n_results}"`.

5. Expose a function named `make_analyze_cache_key`:

```python
def make_analyze_cache_key(query: str, n_results: int) -> str
```

Returns a cache key string in the format `analyze:{hash}` where hash is the MD5 hex digest of `f"{query}:{n_results}"`.

6. All functions must wrap Redis operations in try/except. If Redis is unavailable, log a WARNING and return None for get operations or do nothing for set operations. Cache failures must never cause endpoint failures.

---

## Step 6: Add caching to GET /search in main.py

In the GET /search handler in main.py:

1. Before calling `search_failures`, compute the cache key using `make_search_cache_key(query, n)` from app.cache.
2. Call `get_cached(key)` from app.cache. If a cached result is returned, log INFO with message "cache_hit" and extra fields `endpoint` set to "search" and `query`, then return the cached result immediately.
3. If no cached result, proceed with the existing `search_failures` call.
4. After getting results, call `set_cached(key, response_dict)` to cache the response dict before returning it.
5. Log INFO with message "cache_miss" and extra field `endpoint` set to "search" when no cache hit occurs.

---

## Step 7: Add caching to analyze_failures_task in tasks.py

In app/tasks.py, in the `analyze_failures_task`:

1. Before calling `search_failures` and `analyze_failures`, compute the cache key using `make_analyze_cache_key(query, n_results)` from app.cache.
2. Call `get_cached(key)`. If a cached result exists, log INFO with message "cache_hit" and extra fields `endpoint` set to "analyze" and `query`, then return the cached result immediately without calling ChromaDB or the Claude API.
3. If no cached result, proceed with the existing workflow.
4. After getting results, call `set_cached(key, result_dict)` to cache the result dict before returning it.
5. Log INFO with message "cache_miss" and extra field `endpoint` set to "analyze" when no cache hit occurs.

---

## Step 8: Create app/rate_limiter.py

Create a new file at app/rate_limiter.py.

This module handles per-API-key rate limiting using Redis.

It must:

1. Define a constant `RATE_LIMIT = 30` and `RATE_WINDOW_SECONDS = 60`.

2. Expose a function named `check_rate_limit`:

```python
def check_rate_limit(api_key_name: str) -> tuple[bool, int]
```

This function:
- Builds a Redis key in the format `ratelimit:{api_key_name}`.
- Gets the current count from Redis. If the key does not exist, the count is 0.
- If the count is already at or above RATE_LIMIT, return `(False, 0)` where 0 is the remaining requests.
- Otherwise, increment the count using Redis INCR. If this is the first request (count was 0), set the key expiry to RATE_WINDOW_SECONDS using EXPIRE.
- Return `(True, RATE_LIMIT - new_count)` where new_count is the value after incrementing.
- Wrap all Redis operations in try/except. If Redis is unavailable, log WARNING and return `(True, -1)` to fail open. Rate limit failures must never block requests.

---

## Step 9: Add rate limiting to protected endpoints in main.py

Add rate limit checking to all protected endpoints except GET /health.

For each protected endpoint handler that has `api_key: APIKeyORM = Depends(require_api_key)`:

1. Call `check_rate_limit(api_key.name)` from app.rate_limiter.
2. If the result is `(False, 0)`, return HTTP 429 with this response body:

```json
{
  "detail": "Rate limit exceeded. Maximum 30 requests per minute per API key."
}
```

3. Add the remaining request count as a response header `X-RateLimit-Remaining` on successful responses.

For endpoints that return a direct Response object this is straightforward. For endpoints that return a dict (FastAPI auto-serializes), wrap the return in a JSONResponse and add the header there.

Apply rate limiting to these endpoints:
- POST /results
- GET /results
- GET /results/{id}
- GET /search
- POST /analyze
- GET /analyze/{task_id}
- POST /agent
- GET /agent/{task_id}
- POST /investigate/{suite_id}
- GET /investigate/result/{task_id}
- POST /keys (admin endpoint, rate limit applies)

Do not apply rate limiting to GET /health.

---

## Step 10: Tests

Add a new test file at tests/test_optimization.py.

Write pytest tests that cover:

1. GET /search returns an `X-Response-Time-Ms` header. Assert the value is a valid float string.

2. GET /search returns an `X-RateLimit-Remaining` header on a successful response.

3. GET /search returns HTTP 429 when the rate limit is exceeded. Mock `check_rate_limit` to return `(False, 0)`.

4. GET /search returns a cached result on the second call with the same query. Mock `get_cached` to return a pre-built result dict on the second call and assert `search_failures` was only called once.

5. POST /analyze returns HTTP 429 when the rate limit is exceeded. Mock `check_rate_limit` to return `(False, 0)`.

6. Test `check_rate_limit` returns `(True, 29)` on first call and `(True, 28)` on second call using a real in-memory Redis mock. Use `fakeredis` for this test if available, otherwise mock the Redis client.

7. Test `check_rate_limit` returns `(True, -1)` when Redis is unavailable. Mock the Redis client to raise a connection error.

8. Test `get_cached` returns None when Redis is unavailable. Mock the Redis client to raise a connection error.

Use unittest.mock.patch for all mocks. Use the existing TestClient pattern.

---

## Expected file changes summary

- app/middleware.py: add latency measurement and request_complete log event
- app/rag.py: add claude_api_call log event with token usage and cost
- app/agent.py: add accumulated token tracking and claude_api_call log event
- app/investigator.py: add claude_api_call log event with token usage and cost
- app/cache.py: new file
- app/rate_limiter.py: new file
- app/main.py: add cache checks to GET /search, add rate limit checks to all protected endpoints, add X-RateLimit-Remaining header
- app/tasks.py: add cache checks to analyze_failures_task
- tests/test_optimization.py: new test file
