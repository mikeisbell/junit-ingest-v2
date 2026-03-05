# INSTRUCTIONS_EMBEDDINGS.md

## Goal

Extend the JUnit XML ingestion service to support semantic search over failure messages.

When a test result is ingested via POST /results, embed each failed test case's failure message and store it in ChromaDB. Add a GET /search endpoint that accepts a natural language query and returns similar failure messages from ChromaDB, with metadata linking back to the Postgres records.

---

## Constraints

- Do not modify the parsing logic in parser.py.
- Do not change the Pydantic models.
- Do not change the existing ORM models in db_models.py.
- Keep the existing POST /results behavior intact. The Postgres write path must continue to work exactly as before. ChromaDB is an addition, not a replacement.
- Use chromadb version 0.4.x Python client.
- Use ChromaDB's default embedding function (DefaultEmbeddingFunction). Do not add a separate embeddings library or call an external API.

---

## Step 1: Add ChromaDB to Docker Compose

The current docker-compose.yml looks like this:

```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@postgres:5432/junit_ingest
    depends_on:
      postgres:
        condition: service_healthy

  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: junit_ingest
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5
```

Make the following changes:

1. Change the api service host port mapping from `"8000:8000"` to `"8001:8000"`. The uvicorn process inside the container still runs on port 8000. This change frees host port 8000 for ChromaDB and avoids a port conflict.

2. Add the following environment variables to the api service:
   - CHROMA_HOST=chromadb
   - CHROMA_PORT=8000

3. Add chromadb to the api service depends_on block with condition: service_started.

4. Add a new chromadb service using the image `chromadb/chroma:latest`.

Set the following environment variables on the chromadb service:

- IS_PERSISTENT=TRUE
- ANONYMIZED_TELEMETRY=FALSE

Do not expose any host port for the chromadb service. It is internal to the Compose network only. The api service reaches it at `chromadb:8000`.

Add a named volume called `chroma_data` and mount it to the chromadb container at `/chroma/chroma`.

Declare the `chroma_data` volume in a top-level volumes block alongside any existing volumes.

---

## Step 2: Add chromadb to requirements

Add `chromadb==0.4.24` to requirements.txt.

---

## Step 3: Create app/vector_store.py

Create a new file at app/vector_store.py.

This module is responsible for all ChromaDB interaction.

It must:

1. Create a ChromaDB HttpClient that connects to the host and port read from environment variables CHROMA_HOST (default: "chromadb") and CHROMA_PORT (default: 8000).

2. Get or create a collection named "failure_messages". Use ChromaDB's DefaultEmbeddingFunction for this collection.

3. Expose a function named `embed_failures` with this signature:

```python
def embed_failures(suite_id: int, test_cases: list[dict]) -> None
```

This function receives the integer Postgres ID of the persisted TestSuiteResultORM record and a list of dicts. Each dict has these keys: `test_case_id` (int), `name` (str), `failure_message` (str or None).

For each test case where failure_message is not None and not empty, add a document to the collection:

- document: the failure_message string
- id: a string in the format "tc-{test_case_id}"
- metadata: a dict with keys `suite_id` (int), `test_case_id` (int), and `name` (str)

Skip any test case where failure_message is None or empty string.

If the collection already contains a document with the same id, upsert it (use collection.upsert, not collection.add).

4. Expose a function named `search_failures` with this signature:

```python
def search_failures(query: str, n_results: int = 5) -> list[dict]
```

This function queries the collection using query_texts=[query] and n_results=n_results.

Return a list of dicts. Each dict must have these keys:

- `test_case_id`: int, from metadata
- `suite_id`: int, from metadata
- `name`: str, from metadata
- `failure_message`: str, the document text
- `distance`: float, the similarity distance from ChromaDB results

Sort the results by distance ascending (closest match first).

If the collection is empty or ChromaDB returns no results, return an empty list.

---

## Step 4: Call embed_failures from the ingest endpoint

In main.py, import embed_failures from app.vector_store.

After the Postgres commit in the POST /results handler, call embed_failures.

Pass the integer ID of the newly created TestSuiteResultORM record as suite_id.

Build the test_cases list from the persisted ORM child records. Each dict must include test_case_id (the ORM record's integer id), name, and failure_message.

Only call embed_failures if there is at least one failed test case with a non-empty failure message. Do not call it for results with no failures.

If embed_failures raises an exception, log the error but do not fail the HTTP response. The Postgres write is the source of truth. ChromaDB is a secondary store.

---

## Step 5: Add GET /search endpoint

Add a new endpoint to main.py:

```
GET /search?q={query}&n={n_results}
```

Parameters:

- q: required string, the search query
- n: optional integer, number of results to return, default 5, minimum 1, maximum 20

Call search_failures(query=q, n_results=n) from app.vector_store.

Return a JSON response with this structure:

```json
{
  "query": "the query string",
  "results": [
    {
      "test_case_id": 42,
      "suite_id": 7,
      "name": "test_login_flow",
      "failure_message": "AssertionError: Expected 200 but got 404",
      "distance": 0.312
    }
  ]
}
```

If there are no results, return the same structure with an empty results array. Do not return a 404.

If the query string q is empty or whitespace only, return HTTP 400 with a message of "Query parameter q is required."

---

## Step 6: Tests

Add a new test file at tests/test_search.py.

Write pytest tests that cover:

1. Ingesting a JUnit XML file with at least one failure, then calling GET /search with a query that should match the failure. Assert that the response contains at least one result and that the distance field is a float.

2. Calling GET /search with an empty query string. Assert that the response is HTTP 400.

3. Calling GET /search when no failures have been ingested. Assert that the response is HTTP 200 and results is an empty list.

Use the existing TestClient pattern from the current test suite. Do not connect to a real ChromaDB instance in tests. Mock the search_failures and embed_failures functions using unittest.mock.patch so tests run without Docker.

---

## Expected file changes summary

- docker-compose.yml: add chromadb service and named volume
- requirements.txt: add chromadb==0.4.24
- app/vector_store.py: new file
- app/main.py: import and call embed_failures after Postgres commit, add GET /search endpoint
- tests/test_search.py: new test file
