# INSTRUCTIONS_RELIABILITY.md

## Goal

Add Redis and Celery to the JUnit XML ingestion service. Move the embedding step out of the POST /results request cycle into a Celery background task. Convert POST /analyze into an async job submission endpoint that returns a task ID. Add GET /analyze/{task_id} to poll for results. Store task results in Redis.

---

## Constraints

- Do not modify parser.py, models.py, or vector_store.py interfaces.
- Do not change the response shape of GET /results or GET /results/{id}.
- Do not change the response shape of GET /search.
- Do not remove the require_api_key dependency from any protected endpoint.
- Use celery[redis] as the Celery broker and result backend. Both use the same Redis instance.
- Read the Redis URL from environment variable REDIS_URL with default `redis://redis:6379/0`.
- Task results must be stored in Redis with a 24 hour expiry.
- Use the existing structured logging pattern from app/logging_config.py inside Celery tasks.

---

## Step 1: Add Redis and Celery to Docker Compose

The current docker-compose.yml has api, postgres, and chromadb services.

Add a redis service:
- Image: `redis:7-alpine`
- No host port exposure. Internal to the Compose network only.
- Add a named volume `redis_data` mounted at `/data` for persistence.
- Add a healthcheck: `redis-cli ping` with interval 5s, timeout 5s, retries 5.

Add the following to the api service:
- Environment variable: `REDIS_URL=redis://redis:6379/0`
- depends_on redis with condition: service_healthy.

Add a new celery worker service:
- Build from the same Dockerfile as the api service using `build: .`
- Command: `celery -A app.celery_app worker --loglevel=info`
- Environment variables: same as the api service (DATABASE_URL, REDIS_URL, CHROMA_HOST, CHROMA_PORT, ANTHROPIC_API_KEY).
- depends_on postgres, redis, and chromadb all with condition: service_healthy or service_started as appropriate.
- Do not expose any ports.

Declare redis_data in the top-level volumes block.

---

## Step 2: Add celery[redis] to requirements.txt

Add `celery[redis]` to requirements.txt. Do not pin a specific version.

---

## Step 3: Create app/celery_app.py

Create a new file at app/celery_app.py.

This module creates and configures the Celery application instance.

It must:

1. Create a Celery app instance named `celery_app` using the application name `"junit_ingest"`.

2. Read the broker URL and result backend URL from the environment variable REDIS_URL with default `redis://redis:6379/0`. Use the same value for both broker and backend.

3. Set the following configuration:
   - `result_expires`: 86400 (24 hours in seconds)
   - `task_serializer`: "json"
   - `result_serializer`: "json"
   - `accept_content`: ["json"]
   - `timezone`: "UTC"

4. Export the `celery_app` instance so tasks can import it.

---

## Step 4: Create app/tasks.py

Create a new file at app/tasks.py.

This module defines all Celery tasks.

It must define two tasks:

**Task 1: embed_failures_task**

```python
@celery_app.task(bind=True, max_retries=3, default_retry_delay=5)
def embed_failures_task(self, suite_id: int, test_cases: list) -> dict
```

This task:
1. Calls `embed_failures(suite_id=suite_id, test_cases=test_cases)` from app.vector_store.
2. On success, logs INFO with message "embed_task_complete" and extra field `suite_id`.
3. On exception, logs ERROR with message "embed_task_failed" and extra fields `suite_id` and `error`. Retries up to 3 times with a 5 second delay using `self.retry(exc=exc)`.
4. Returns `{"suite_id": suite_id, "status": "complete"}` on success.

**Task 2: analyze_failures_task**

```python
@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def analyze_failures_task(self, query: str, n_results: int) -> dict
```

This task:
1. Calls `search_failures(query=query, n_results=n_results)` from app.vector_store.
2. Calls `analyze_failures(query=query, failures=results)` from app.rag.
3. On success, logs INFO with message "analyze_task_complete" and extra fields `query` and `failures_used`.
4. On exception, logs ERROR with message "analyze_task_failed" and extra fields `query` and `error`. Retries up to 3 times with a 10 second delay.
5. Returns `{"query": query, "failures_used": len(results), "analysis": analysis_text}` on success.

---

## Step 5: Update POST /results in main.py

Replace the direct `embed_failures` call in the POST /results handler with a Celery task dispatch.

After the Postgres commit:
1. Build the test_cases list from the persisted ORM child records as before.
2. Instead of calling `embed_failures` directly, call `embed_failures_task.delay(suite_id=suite_id, test_cases=test_cases)`.
3. Log INFO with message "embed_task_queued" and extra field `suite_id`.
4. Remove the try/except block that was wrapping the direct embed_failures call.

The POST /results response shape does not change.

---

## Step 6: Update POST /analyze in main.py

Replace the synchronous POST /analyze handler with an async job submission endpoint.

The endpoint must:
1. Validate that query is not empty or whitespace. Return HTTP 400 with message "query is required" if it is.
2. Dispatch `analyze_failures_task.delay(query=query, n_results=n)`.
3. Log INFO with message "analyze_task_queued" and extra field `query`.
4. Return HTTP 202 with this response body:

```json
{
  "task_id": "the-celery-task-id",
  "status": "pending"
}
```

---

## Step 7: Add GET /analyze/{task_id} endpoint

Add a new endpoint to main.py:

```
GET /analyze/{task_id}
```

This endpoint requires Bearer token auth.

It must:
1. Use `celery_app.AsyncResult(task_id)` to retrieve the task result.
2. If the task state is PENDING or STARTED, return HTTP 200:

```json
{
  "task_id": "abc-123",
  "status": "pending"
}
```

3. If the task state is SUCCESS, return HTTP 200:

```json
{
  "task_id": "abc-123",
  "status": "complete",
  "query": "why are my tests failing?",
  "failures_used": 3,
  "analysis": "Based on the retrieved failures..."
}
```

4. If the task state is FAILURE, return HTTP 200:

```json
{
  "task_id": "abc-123",
  "status": "failed",
  "error": "the exception message"
}
```

5. Never return a 404 for an unknown task ID. Return the pending shape instead, as Celery returns PENDING for unknown IDs.

---

## Step 8: Update GET /health endpoint

Add a Redis health check to the existing /health endpoint.

Check Redis by importing redis and calling `redis.from_url(REDIS_URL).ping()`. If it succeeds, status is "ok". If it raises, status is "error".

Update the response structure to include redis alongside postgres and chromadb:

```json
{
  "status": "ok",
  "dependencies": {
    "postgres": {"status": "ok"},
    "chromadb": {"status": "ok"},
    "redis": {"status": "ok"}
  }
}
```

Return HTTP 503 if any dependency is degraded.

---

## Step 9: Tests

Add a new test file at tests/test_reliability.py.

Write pytest tests that cover:

1. POST /results with a valid Bearer token dispatches the embed task and returns HTTP 200. Mock `embed_failures_task.delay` and assert it was called with the correct suite_id.

2. POST /analyze with a valid Bearer token returns HTTP 202 and a response body containing `task_id` and `status` equal to "pending". Mock `analyze_failures_task.delay`.

3. GET /analyze/{task_id} when the task is pending returns HTTP 200 with status "pending". Mock `celery_app.AsyncResult` to return a mock with state "PENDING".

4. GET /analyze/{task_id} when the task is complete returns HTTP 200 with status "complete" and an analysis field. Mock `celery_app.AsyncResult` to return a mock with state "SUCCESS" and the expected result dict.

5. GET /analyze/{task_id} when the task failed returns HTTP 200 with status "failed". Mock `celery_app.AsyncResult` to return a mock with state "FAILURE".

6. GET /health returns HTTP 200 with redis status "ok" when all dependencies are healthy. Mock postgres, chromadb, and redis checks.

7. GET /health returns HTTP 503 with status "degraded" when Redis is unreachable. Mock redis ping to raise.

Use unittest.mock.patch for all mocks. Do not require a running Redis instance for tests.

---

## Expected file changes summary

- docker-compose.yml: add redis service, celery worker service, redis_data volume, REDIS_URL env var on api service
- requirements.txt: add celery[redis]
- app/celery_app.py: new file
- app/tasks.py: new file
- app/main.py: update POST /results to dispatch embed task, update POST /analyze to dispatch analyze task and return 202, add GET /analyze/{task_id}, update /health to include redis
- tests/test_reliability.py: new test file
