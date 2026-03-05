# INSTRUCTIONS_SECURITY.md

## Goal

Add Bearer token API key authentication to the JUnit XML ingestion service. API keys are stored in Postgres. All endpoints except GET /health require a valid Bearer token. Add a management endpoint to issue new API keys.

---

## Constraints

- Do not modify parser.py, models.py, vector_store.py, or rag.py.
- Do not change any existing endpoint response shapes.
- Do not add authentication to GET /health.
- Store API keys hashed in Postgres. Never store or log the plaintext key after issuance.
- Use the `secrets` module from the Python standard library to generate keys. Do not use UUID for key generation.
- Use `hashlib.sha256` to hash keys before storing. Do not use bcrypt or any third-party hashing library.
- Read a bootstrap admin token from the environment variable ADMIN_TOKEN. This token is used only to call POST /keys to issue new API keys.

---

## Step 1: Add API key ORM model to db_models.py

Add a new SQLAlchemy ORM model named `APIKeyORM` to db_models.py.

It must have these columns:
- `id`: integer primary key, autoincrement
- `key_hash`: string, unique, not nullable. Stores the SHA256 hex digest of the plaintext key.
- `name`: string, not nullable. A human-readable label for the key, e.g. "dev" or "ci".
- `created_at`: datetime, not nullable, default to UTC now.
- `is_active`: boolean, not nullable, default True.

---

## Step 2: Create app/auth.py

Create a new file at app/auth.py.

This module handles all authentication logic.

It must:

1. Define a function named `hash_key`:

```python
def hash_key(plaintext: str) -> str
```

Returns the SHA256 hex digest of the plaintext string.

2. Define a function named `generate_key`:

```python
def generate_key() -> str
```

Uses `secrets.token_urlsafe(32)` to generate a new plaintext API key string. Returns it.

3. Define a FastAPI dependency function named `require_api_key`:

```python
async def require_api_key(
    credentials: HTTPAuthorizationCredentials = Security(HTTPBearer()),
    db: Session = Depends(get_db)
) -> APIKeyORM
```

This function:
- Takes the Bearer token from the Authorization header via FastAPI's HTTPBearer security scheme.
- Hashes the token using hash_key.
- Queries the database for an APIKeyORM record where key_hash matches and is_active is True.
- If no matching active key is found, raises HTTPException with status code 401 and detail "Invalid or inactive API key".
- If a matching key is found, returns the APIKeyORM record.

4. Define a function named `require_admin_token`:

```python
def require_admin_token(x_admin_token: str = Header(...))
```

This function:
- Reads the expected admin token from the environment variable ADMIN_TOKEN.
- If ADMIN_TOKEN is not set, raises HTTPException 500 with detail "Admin token not configured".
- If the provided x_admin_token header does not match the ADMIN_TOKEN value, raises HTTPException 401 with detail "Invalid admin token".
- If it matches, returns without raising.

---

## Step 3: Add POST /keys endpoint to main.py

Add a new endpoint to main.py:

```
POST /keys
```

This endpoint issues a new API key. It requires the X-Admin-Token header to match the ADMIN_TOKEN environment variable. It does not require a Bearer token.

Request body:

```json
{
  "name": "dev"
}
```

The `name` field is required and must be a non-empty string.

The endpoint must:

1. Call `require_admin_token` as a dependency.
2. Generate a new plaintext key using `generate_key()`.
3. Hash it using `hash_key()`.
4. Create a new APIKeyORM record with the hash and name. Commit it to Postgres.
5. Return HTTP 201 with this response body:

```json
{
  "key": "the-plaintext-key-shown-only-once",
  "name": "dev",
  "created_at": "2026-01-01T00:00:00"
}
```

Include a comment in the code noting that this is the only time the plaintext key is returned. It is not stored.

6. Log an INFO event with message "api_key_created" and extra field `name`.

---

## Step 4: Add require_api_key dependency to protected endpoints

In main.py, add `require_api_key` as a dependency to these endpoints:

- POST /results
- GET /results
- GET /results/{id}
- GET /search
- POST /analyze

Do this by adding `api_key: APIKeyORM = Depends(require_api_key)` to each handler signature.

Do not add it to GET /health or POST /keys.

---

## Step 5: Add ADMIN_TOKEN to docker-compose.yml

In the api service environment block, add:

```
- ADMIN_TOKEN=${ADMIN_TOKEN}
```

---

## Step 6: Update structured logging to include key name

In the log events for POST /results, GET /search, and POST /analyze, add an extra field `api_key_name` using the `name` field from the resolved `APIKeyORM` record. This makes it possible to trace which key made which request.

---

## Step 7: Tests

Add a new test file at tests/test_auth.py.

Write pytest tests that cover:

1. POST /results without an Authorization header returns HTTP 403.

2. POST /results with an invalid Bearer token returns HTTP 401.

3. POST /results with a valid Bearer token succeeds and returns HTTP 200.

4. GET /search without an Authorization header returns HTTP 403.

5. GET /health without an Authorization header returns HTTP 200. Health endpoint is public.

6. POST /keys without the X-Admin-Token header returns HTTP 422.

7. POST /keys with an invalid X-Admin-Token returns HTTP 401.

8. POST /keys with a valid X-Admin-Token returns HTTP 201 and a response body containing a `key` field.

9. A key returned by POST /keys can be used to authenticate POST /results successfully.

For tests that require a valid API key, create one in the test setup by directly inserting a hashed key into the test database, then use the plaintext version as the Bearer token. Do not call POST /keys to set up auth in other tests — test concerns should be isolated.

Use the existing TestClient and database fixture patterns from the current test suite.

---

## Step 8: Update README or add a usage note

Add a comment block at the top of app/auth.py explaining the key lifecycle:

```
# API Key Lifecycle
# 1. Operator calls POST /keys with X-Admin-Token header to issue a new key.
# 2. The plaintext key is returned once and never stored.
# 3. The SHA256 hash of the key is stored in Postgres.
# 4. On each request, the Bearer token is hashed and compared against stored hashes.
# 5. Keys can be deactivated by setting is_active=False in the database.
```

---

## Expected file changes summary

- app/db_models.py: add APIKeyORM model
- app/auth.py: new file
- app/main.py: add POST /keys endpoint, add require_api_key dependency to protected endpoints, add api_key_name to log events
- docker-compose.yml: add ADMIN_TOKEN environment variable
- tests/test_auth.py: new test file
