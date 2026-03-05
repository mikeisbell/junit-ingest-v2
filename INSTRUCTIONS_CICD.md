# INSTRUCTIONS_CICD.md

## Goal

Add a GitHub Actions CI pipeline that runs on every push and pull request. The pipeline has three stages that run in sequence: unit tests, Docker build verification, and integration tests against a live Docker Compose stack. Also add a production-appropriate Docker Compose override file and a deployment README.

---

## Constraints

- Do not modify any existing application code.
- Do not modify the existing docker-compose.yml.
- The GitHub Actions workflow must use Ubuntu latest as the runner.
- The integration test stage must spin up the full Docker Compose stack and run a real HTTP request sequence against it.
- Secrets must be read from GitHub Actions secrets, never hardcoded.
- The pipeline must fail fast: if unit tests fail, do not proceed to Docker build or integration tests.

---

## Step 1: Create .github/workflows/ci.yml

Create the directory `.github/workflows/` and create a file named `ci.yml` inside it.

The workflow must:

1. Trigger on push to any branch and on pull requests targeting the main branch.

2. Define a single job named `ci` running on `ubuntu-latest`.

3. Use these GitHub Actions secrets for environment variables throughout the job:
   - `ANTHROPIC_API_KEY`: read from `secrets.ANTHROPIC_API_KEY`
   - `ADMIN_TOKEN`: read from `secrets.ADMIN_TOKEN`

4. Structure the job as these sequential steps:

**Step: Checkout**
Use `actions/checkout@v4`.

**Step: Set up Python**
Use `actions/setup-python@v5` with python-version `"3.12"`.

**Step: Install dependencies**
```bash
pip install -r requirements.txt
```

**Step: Run unit tests**
```bash
pytest tests/ -v --tb=short
```
Set the environment variable `DATABASE_URL=sqlite:///./test_temp.db` for this step only.

**Step: Build Docker images**
```bash
docker compose build
```
This verifies all Dockerfiles build successfully without starting containers.

**Step: Start Docker Compose stack**
```bash
docker compose up -d --wait
```
Set these environment variables for this step:
- `ANTHROPIC_API_KEY`: from secrets
- `ADMIN_TOKEN`: from secrets
- `REDIS_URL=redis://redis:6379/0`

Use `--wait` so the step blocks until all healthchecks pass before continuing.

**Step: Wait for services**
```bash
sleep 5
```
This gives the API and Celery worker a moment to fully initialize after healthchecks pass.

**Step: Run integration tests**
```bash
python tests/integration/test_integration.py
```
Set these environment variables for this step:
- `ANTHROPIC_API_KEY`: from secrets
- `ADMIN_TOKEN`: from secrets
- `SERVICE_URL=http://localhost:8001`

**Step: Print container logs on failure**
Use `if: failure()` condition so this step only runs if a previous step failed.
```bash
docker compose logs
```
This makes debugging CI failures possible without SSH access to the runner.

**Step: Tear down Docker Compose stack**
Use `if: always()` condition so this always runs even if earlier steps failed.
```bash
docker compose down -v
```

---

## Step 2: Create tests/integration/test_integration.py

Create the directory `tests/integration/` and create a file named `test_integration.py` inside it.

This is a standalone Python script that runs integration tests against the live service. It is not a pytest file. It uses only the standard library `urllib.request` and `urllib.error` for HTTP calls so there are no additional dependencies.

The script must:

1. Read `SERVICE_URL` from the environment with default `http://localhost:8001`.
2. Read `ADMIN_TOKEN` from the environment. If not set, print an error and exit with code 1.
3. Define a simple helper function that makes HTTP requests and returns the status code and parsed JSON body.
4. Run these integration test cases in sequence:

**Test 1: Health check**
GET /health. Assert status is 200 and response body `status` equals `"ok"`.

**Test 2: Issue API key**
POST /keys with `X-Admin-Token` header set to ADMIN_TOKEN and body `{"name": "ci"}`.
Assert status is 201 and response body contains a `key` field.
Store the returned key for use in subsequent tests.

**Test 3: Reject unauthenticated request**
POST /results without Authorization header.
Assert status is 403.

**Test 4: Ingest JUnit XML**
POST /results with Bearer token and a hardcoded minimal JUnit XML string as a multipart file upload.

Use this XML:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="IntegrationTestSuite" tests="2" failures="1" errors="0" skipped="0" time="0.5">
  <testcase name="test_pass" time="0.1"/>
  <testcase name="test_fail" time="0.4">
    <failure message="AssertionError: integration test failure">Expected true but got false</failure>
  </testcase>
</testsuite>
```

Assert status is 200 and response body contains `name` equal to `"IntegrationTestSuite"`.

**Test 5: Semantic search**
GET /search?q=assertion+error&n=3 with Bearer token.
Assert status is 200 and response body contains a `results` key.

**Test 6: Submit analyze job**
POST /analyze with Bearer token and body `{"query": "why is the integration test failing?", "n": 3}`.
Assert status is 202 and response body contains `task_id` and `status` equal to `"pending"`.
Store the task_id.

**Test 7: Poll for analyze result**
Poll GET /analyze/{task_id} with Bearer token up to 30 seconds, checking every 2 seconds.
Assert that status eventually becomes `"complete"` or `"failed"`.
If it does not resolve within 30 seconds, fail the test.

5. Print a result line for each test in this format:
```
PASS [Health check]
PASS [Issue API key]
PASS [Reject unauthenticated request]
PASS [Ingest JUnit XML]
PASS [Semantic search]
PASS [Submit analyze job]
PASS [Poll for analyze result]
```

6. Print a final summary:
```
Integration tests complete: 7/7 passed
```

7. If any test fails, print `FAIL [test name] — {reason}` and exit with code 1 after all tests have run. Do not stop on first failure. Run all tests and report all failures at the end.

---

## Step 3: Create docker-compose.prod.yml

Create a new file at `docker-compose.prod.yml` in the project root.

This is a Docker Compose override file for production-appropriate settings. It is used with:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up
```

It must override the base docker-compose.yml with these changes:

1. Remove host port exposures for postgres and chromadb. In production these should not be reachable from outside the host.

2. Add restart policies of `unless-stopped` to the api, celery_worker, postgres, chromadb, and redis services.

3. Add resource limits to the api service:
   - Memory limit: 512m
   - CPU limit: 0.5

4. Add resource limits to the celery_worker service:
   - Memory limit: 512m
   - CPU limit: 0.5

5. Set the api service logging driver to `json-file` with max size `10m` and max file `3`.

---

## Step 4: Create DEPLOYMENT.md

Create a new file at `DEPLOYMENT.md` in the project root.

Write a deployment README that covers:

1. **Prerequisites**: Docker, Docker Compose, and required environment variables (ANTHROPIC_API_KEY, ADMIN_TOKEN).

2. **Local development**: How to start the stack with `docker compose up --build`, how to issue an API key, and how to run the test suite.

3. **Running in production**: How to use docker-compose.prod.yml, what each service does, and how to check service health.

4. **Environment variables**: A table listing every environment variable the service reads, its default value, and whether it is required.

5. **API key management**: How to issue a new key via POST /keys, how to use it as a Bearer token, and how keys are stored.

6. **CI pipeline**: What the GitHub Actions pipeline runs and how to add the required secrets to the GitHub repository.

7. **Monitoring**: How to read structured logs, what the trace_id field is for, and how to use GET /health.

Write it in plain Markdown. Keep it practical and direct. No unnecessary prose.

---

## Step 5: Create tests/integration/__init__.py

Create an empty file at `tests/integration/__init__.py` so the directory is a proper Python package.

---

## Expected file changes summary

- .github/workflows/ci.yml: new file
- tests/integration/__init__.py: new empty file
- tests/integration/test_integration.py: new file
- docker-compose.prod.yml: new file
- DEPLOYMENT.md: new file
