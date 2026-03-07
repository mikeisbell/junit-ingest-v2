# INSTRUCTIONS_DEVREV_INTEGRATION.md

## Goal

Add a DevRev integration to the service. When a CI pipeline posts JUnit XML results and the
failure rate exceeds a configurable threshold, the service automatically creates a DevRev issue
populated with the AI-generated investigation report.

The DevRev client supports two modes controlled by an environment variable:
- Mock mode (DEVREV_MOCK=true): logs the issue payload instead of calling the API
- Live mode (DEVREV_MOCK=false or unset): calls POST https://api.devrev.ai/works.create

All new code must be covered by unit tests with mocked external calls.

---

## Constraints

- Do not modify any existing endpoints.
- Do not modify any existing test files.
- Do not add any new dependencies to requirements.txt.
- Use only httpx (already available via fastapi) or urllib for the DevRev API call.
- The webhook endpoint must not require authentication. It will be called by GitHub Actions.
- All other existing endpoints remain protected by Bearer token auth.
- The investigator pipeline (layers 8 and 9) must not be modified.

---

## New environment variables

Add these to docker-compose.yml under the api service environment block:

- DEVREV_PAT: DevRev personal access token. Required in live mode. Ignored in mock mode.
- DEVREV_PART_ID: The part ID to associate the issue with (e.g. PROD-1). Required in live mode.
- DEVREV_OWNER_ID: The DevRev user DON ID to assign the issue to. Required in live mode.
- DEVREV_MOCK: Set to "true" to enable mock mode. Default is "false".
- CI_FAILURE_THRESHOLD: Float between 0 and 1. If the failure rate of an ingested suite exceeds
  this value, a DevRev issue is created. Default is 0.2 (20%).

In docker-compose.yml, wire these as:
```
DEVREV_PAT: ${DEVREV_PAT:-}
DEVREV_PART_ID: ${DEVREV_PART_ID:-PROD-1}
DEVREV_OWNER_ID: ${DEVREV_OWNER_ID:-}
DEVREV_MOCK: ${DEVREV_MOCK:-true}
CI_FAILURE_THRESHOLD: ${CI_FAILURE_THRESHOLD:-0.2}
```

Default DEVREV_MOCK to true so the service works out of the box without credentials.

---

## Step 1: Create app/devrev_client.py

This module is the only place that talks to the DevRev API.

It must:

1. Read these values from environment variables on import:
   - DEVREV_PAT
   - DEVREV_PART_ID
   - DEVREV_OWNER_ID
   - DEVREV_MOCK (parse as bool: "true" -> True, anything else -> False)

2. Define a dataclass named DevRevIssue with these fields:
   - title: str
   - body: str
   - priority: str (default "p2")

3. Define a function named create_issue(issue: DevRevIssue) -> dict that:

   In mock mode:
   - Logs the full payload it would have sent at INFO level using the structured logger
   - The log event name must be "devrev_mock_issue_created"
   - Include title, body, priority, and mock=True in the log fields
   - Returns {"mock": True, "title": issue.title, "status": "logged"}

   In live mode:
   - Builds this request body:
     ```json
     {
       "type": "issue",
       "title": "<issue.title>",
       "body": "<issue.body>",
       "applies_to_part": "<DEVREV_PART_ID>",
       "owned_by": ["<DEVREV_OWNER_ID>"],
       "priority": "<issue.priority>"
     }
     ```
   - POSTs to https://api.devrev.ai/works.create
   - Sets Authorization header to "Bearer <DEVREV_PAT>"
   - Sets Content-Type to application/json
   - Uses urllib.request (no new dependencies)
   - On success (HTTP 201), logs event "devrev_issue_created" with title and work item id
     from the response and returns the parsed response body
   - On failure, logs event "devrev_issue_failed" with status code and response body,
     and raises a RuntimeError with the status code and response body included in the message
   - If DEVREV_PAT, DEVREV_PART_ID, or DEVREV_OWNER_ID are not set in live mode,
     raise a RuntimeError with a clear message before making any API call

---

## Step 2: Create app/ci_webhook.py

This module contains the webhook endpoint logic, separate from main.py.

It must define a function named process_ci_webhook that:

1. Accepts a parsed TestSuite object (the same Pydantic model used by POST /results)
   and a db Session.

2. Reads CI_FAILURE_THRESHOLD from environment. Default 0.2. Parse as float.

3. Calculates failure rate as: suite.failures / suite.tests if suite.tests > 0 else 0.0

4. If failure rate is 0 or suite.failures is 0, returns immediately without creating an issue.

5. If failure rate is below CI_FAILURE_THRESHOLD, logs event "ci_threshold_not_met" with
   suite name, failure rate, and threshold, then returns without creating an issue.

6. If failure rate meets or exceeds threshold:
   a. Calls investigate_suite() from app.investigator directly (synchronous, not via Celery)
      passing the suite object. Note: investigate_suite accepts a TestSuite object.
   b. Builds a DevRevIssue from the investigation report:
      - title: "CI Failure: {suite.name} ({failures}/{tests} tests failed)"
        where failures and tests come from the suite object
      - body: format the report as plain text including:
        - Summary from report["summary"]
        - Root cause hypotheses from report["root_cause_hypotheses"] (list each with confidence)
        - Recommended next steps from report["recommended_next_steps"]
        - A footer line: "Generated by junit-ingest-v2 AI investigator"
      - priority: "p1" if failure rate >= 0.5 else "p2"
   c. Calls create_issue() from app.devrev_client
   d. Logs event "ci_devrev_issue_dispatched" with suite name, failure rate, and mock status
   e. Returns the result from create_issue()

7. Wrap the investigate_suite call and create_issue call in a try/except. If either raises,
   log event "ci_webhook_error" with the error message and re-raise.

---

## Step 3: Add POST /webhook/ci to app/main.py

Add a new endpoint POST /webhook/ci.

It must:

1. Accept a file upload named "file" (same multipart format as POST /results).

2. NOT require authentication. Do not apply the require_api_key dependency.
   Add a comment explaining this is intentionally unauthenticated for CI pipeline use.

3. Parse the uploaded XML using the existing parse_junit_xml function from app.parser.

4. Call process_ci_webhook(suite, db) from app.ci_webhook.

5. Return HTTP 200 with this response body:
   ```json
   {
     "suite": "<suite name>",
     "tests": <int>,
     "failures": <int>,
     "failure_rate": <float rounded to 4 decimal places>,
     "issue_created": <true if create_issue was called, false otherwise>,
     "devrev_result": <the dict returned by process_ci_webhook, or null if no issue was created>
   }
   ```

6. If parsing fails, return HTTP 422 with a clear error message.

7. If process_ci_webhook raises, return HTTP 500 with the error message.

---

## Step 4: Create tests/test_devrev_client.py

Create unit tests for app/devrev_client.py.

Tests must cover:

1. test_mock_mode_returns_logged_result: Set DEVREV_MOCK=true. Call create_issue with a
   DevRevIssue. Assert the return value has mock=True and status="logged".

2. test_mock_mode_does_not_call_api: Set DEVREV_MOCK=true. Patch urllib.request.urlopen.
   Call create_issue. Assert urlopen was never called.

3. test_live_mode_missing_credentials_raises: Set DEVREV_MOCK=false and leave DEVREV_PAT
   empty. Assert create_issue raises RuntimeError.

4. test_live_mode_success: Set DEVREV_MOCK=false and set all required env vars. Patch
   urllib.request.urlopen to return a mock response with status 201 and a JSON body
   containing a work item id. Assert create_issue returns the parsed response body.

5. test_live_mode_api_failure_raises: Set DEVREV_MOCK=false and set all required env vars.
   Patch urllib.request.urlopen to return a mock response with status 400. Assert
   create_issue raises RuntimeError.

Use monkeypatch to set environment variables in each test. Re-import or reload the module
as needed since env vars are read on import. Alternatively, patch os.environ directly
within each test function using monkeypatch.setenv.

---

## Step 5: Create tests/test_ci_webhook.py

Create unit tests for app/ci_webhook.py and POST /webhook/ci.

Tests must cover:

1. test_below_threshold_no_issue: Call process_ci_webhook with a suite where failure rate
   is below CI_FAILURE_THRESHOLD. Mock investigate_suite and create_issue. Assert
   create_issue was never called.

2. test_zero_failures_no_issue: Call process_ci_webhook with a suite where failures=0.
   Assert create_issue was never called.

3. test_above_threshold_creates_issue: Call process_ci_webhook with a suite where failure
   rate exceeds threshold. Mock investigate_suite to return a valid report dict. Mock
   create_issue to return {"mock": True, "status": "logged"}. Assert create_issue was called
   once with a DevRevIssue whose title starts with "CI Failure:".

4. test_high_failure_rate_sets_p1_priority: Call process_ci_webhook with a suite where
   failure rate is >= 0.5. Mock investigate_suite and create_issue. Assert the DevRevIssue
   passed to create_issue has priority="p1".

5. test_webhook_endpoint_no_auth_required: POST to /webhook/ci with a valid XML file and
   NO Authorization header. Assert the response is not 401 or 403.

6. test_webhook_endpoint_returns_correct_shape: POST to /webhook/ci with a valid XML file.
   Mock process_ci_webhook to return {"mock": True}. Assert response contains suite, tests,
   failures, failure_rate, issue_created, and devrev_result keys.

Use pytest fixtures and monkeypatch as needed. Use the TestClient from fastapi.testclient.

---

## Expected file changes summary

- app/devrev_client.py: new file
- app/ci_webhook.py: new file
- app/main.py: add POST /webhook/ci endpoint
- docker-compose.yml: add 5 new environment variables under api service
- tests/test_devrev_client.py: new file
- tests/test_ci_webhook.py: new file
