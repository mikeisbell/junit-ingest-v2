# INSTRUCTIONS_OBSERVABILITY.md

## Goal

Add structured JSON logging, trace IDs, and a /health endpoint to the JUnit XML ingestion service. Every significant operation must emit a structured log event. Every request must carry a trace ID through the full call chain. The /health endpoint must report the status of all dependencies.

---

## Constraints

- Do not modify parser.py, models.py, db_models.py, or vector_store.py logic. You may add logging calls inside these files but do not change their interfaces or behavior.
- Do not change any existing endpoint behavior or response shapes.
- Use Python's standard logging module. Do not add a third-party logging library.
- All log output must be valid JSON, one object per line. No plain text log lines.
- Do not log the ANTHROPIC_API_KEY or DATABASE_URL values. Log their presence as true or false only.

---

## Step 1: Create app/logging_config.py

Create a new file at app/logging_config.py.

This module configures structured JSON logging for the entire application.

It must:

1. Define a custom logging formatter class named `JSONFormatter` that extends `logging.Formatter`.

The `format` method must return a JSON string with these fields for every log record:
- `timestamp`: ISO 8601 UTC string
- `level`: the log level name (INFO, WARNING, ERROR, etc.)
- `logger`: the logger name
- `message`: the log message
- `trace_id`: the trace ID for the current request, or null if not in a request context
- Any extra fields passed via the `extra` parameter to the log call

2. Define a function named `configure_logging` that:
- Sets the root logger level to INFO
- Removes any existing handlers from the root logger
- Adds a StreamHandler to stdout using JSONFormatter
- Suppresses noisy logs from uvicorn.access, httpx, and chromadb loggers by setting them to WARNING level

3. Use a Python `contextvars.ContextVar` named `trace_id_var` to store the trace ID for the current request context. Initialize it with a default of `None`. Export it from this module so middleware can set it.

---

## Step 2: Create app/middleware.py

Create a new file at app/middleware.py.

This module defines FastAPI middleware for trace ID injection.

It must define a class named `TraceIDMiddleware` that extends `starlette.middleware.base.BaseHTTPMiddleware`.

In the `dispatch` method:
1. Read the `X-Trace-ID` header from the incoming request. If it is present and non-empty, use it as the trace ID. If it is absent, generate a new UUID4 string.
2. Set the trace ID on `trace_id_var` from app.logging_config using `trace_id_var.set(trace_id)`.
3. Add the trace ID as a response header `X-Trace-ID` on the outgoing response.
4. Call and await `call_next(request)` and return the response.

---

## Step 3: Update app/main.py

Make the following changes to main.py:

1. Import and call `configure_logging` from app.logging_config at module level, before the FastAPI app is created.

2. Add `TraceIDMiddleware` from app.middleware to the FastAPI app using `app.add_middleware`.

3. Add a logger at module level: `logger = logging.getLogger(__name__)`.

4. In the POST /results handler, add structured log events at these points:
   - On entry: log level INFO, message "ingest_started", include extra fields `filename` (the uploaded filename) and `content_length` (the file size in bytes).
   - After successful Postgres commit: log level INFO, message "ingest_complete", include extra fields `suite_id` (the new ORM record ID), `total_tests`, `total_failures`.
   - After successful embed_failures call: log level INFO, message "embed_complete", include extra field `suite_id`.
   - If embed_failures raises: log level ERROR, message "embed_failed", include extra field `error` (the exception string).
   - On parse error: log level WARNING, message "ingest_parse_error", include extra field `error`.

5. In the GET /search handler, add structured log events:
   - On entry: log level INFO, message "search_started", include extra field `query` (the query string).
   - On completion: log level INFO, message "search_complete", include extra fields `query` and `result_count`.

6. In the POST /analyze handler, add structured log events:
   - On entry: log level INFO, message "analyze_started", include extra field `query`.
   - On completion: log level INFO, message "analyze_complete", include extra fields `query` and `failures_used`.
   - On 502 error: log level ERROR, message "analyze_failed", include extra field `error`.

---

## Step 4: Add GET /health endpoint

Add a new endpoint to main.py:

```
GET /health
```

This endpoint checks all dependencies and returns their status.

It must:

1. Check Postgres by executing a `SELECT 1` query using a SQLAlchemy session. If it succeeds, status is "ok". If it raises, status is "error" and include the exception string.

2. Check ChromaDB by calling `_get_client().heartbeat()` from app.vector_store. If it returns without raising, status is "ok". If it raises, status is "error" and include the exception string.

3. Return HTTP 200 with this response structure if all dependencies are healthy:

```json
{
  "status": "ok",
  "dependencies": {
    "postgres": {"status": "ok"},
    "chromadb": {"status": "ok"}
  }
}
```

4. Return HTTP 503 with the same structure if any dependency status is "error":

```json
{
  "status": "degraded",
  "dependencies": {
    "postgres": {"status": "ok"},
    "chromadb": {"status": "error", "detail": "Connection refused"}
  }
}
```

5. The /health endpoint must never raise an unhandled exception. Wrap all dependency checks in try/except.

6. Do not add authentication to the /health endpoint. It must be publicly accessible.

---

## Step 5: Export _get_client from vector_store.py

In app/vector_store.py, ensure `_get_client` is importable. If it is currently a module-level private function, that is fine. The health endpoint in main.py will import it directly as `from app.vector_store import _get_client`.

---

## Step 6: Tests

Add a new test file at tests/test_observability.py.

Write pytest tests that cover:

1. POST /results returns an `X-Trace-ID` header in the response.

2. GET /search returns an `X-Trace-ID` header in the response.

3. POST /analyze returns an `X-Trace-ID` header in the response.

4. If the request includes an `X-Trace-ID` header, the response echoes the same value back.

5. GET /health returns HTTP 200 and a body with `status` equal to `"ok"` when all dependencies are reachable. Mock both the Postgres check and the ChromaDB heartbeat to return successfully.

6. GET /health returns HTTP 503 and a body with `status` equal to `"degraded"` when ChromaDB is unreachable. Mock the ChromaDB heartbeat to raise an exception.

Use unittest.mock.patch for all dependency mocks. Use the existing TestClient pattern.

---

## Expected file changes summary

- app/logging_config.py: new file
- app/middleware.py: new file
- app/main.py: add logging calls, middleware registration, /health endpoint
- app/vector_store.py: ensure _get_client is importable
- tests/test_observability.py: new test file
