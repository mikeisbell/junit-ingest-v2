# INSTRUCTIONS_COMMENTS.md

## Goal

Add docstrings and inline comments to four modules to improve code readability and
demonstrate production-quality engineering practices. Do not change any logic, imports,
function signatures, or behavior. Only add comments and docstrings.

---

## Constraints

- Do not modify any logic, control flow, or variable names.
- Do not add, remove, or reorder any imports.
- Do not change any function signatures or return types.
- Do not modify any existing tests.
- Comments must be accurate, concise, and written for a senior engineer audience.
- Avoid obvious comments like "# increment counter". Explain the why, not the what.
- Every function and class must have a docstring.
- Complex logic blocks must have an inline comment explaining the reasoning.

---

## Module 1: app/devrev_client.py

Add the following:

1. A module-level docstring explaining:
   - This module is the single integration point between junit-ingest-v2 and the DevRev API
   - It supports two modes: mock mode for development/demo and live mode for production
   - Mock mode is controlled by the DEVREV_MOCK environment variable

2. A docstring on the DevRevIssue dataclass explaining its purpose and fields.

3. Inline comments in create_issue() explaining:
   - Why mock mode logs instead of calling the API
   - Why credentials are validated before building the request in live mode
   - Why urllib.request is used instead of a third-party HTTP library
   - Why the response status is checked for 201 specifically
   - What information is logged on success and failure and why

---

## Module 2: app/ci_webhook.py

Add the following:

1. A module-level docstring explaining:
   - This module processes CI pipeline webhook events
   - It ingests JUnit XML results, runs AI-powered failure analysis, and creates
     DevRev issues when failure rates exceed a configurable threshold
   - The threshold is controlled by the CI_FAILURE_THRESHOLD environment variable

2. A docstring on process_ci_webhook() explaining:
   - Its inputs and what it does with them
   - The threshold evaluation logic
   - The relationship between this function and investigate_suite()
   - Why the suite is saved to Postgres before calling investigate_suite()

3. Inline comments explaining:
   - Why failure rate is calculated as failures / tests rather than using errors
   - Why the suite must be persisted before investigation can run
   - Why p1 priority is assigned at >= 0.5 failure rate
   - Why investigate_suite is called synchronously here instead of via Celery

---

## Module 3: app/investigator.py

Add the following:

1. A module-level docstring explaining:
   - This module implements the agentic investigation pattern (Layer 8)
   - Unlike the tool use agent in agent.py, the investigator uses a fixed
     deterministic workflow: your code controls the steps, Claude synthesizes at the end
   - This pattern trades autonomy for predictability and cost control

2. A docstring on investigate_suite() explaining all steps in the pipeline.

3. Inline comments explaining:
   - Why the workflow is fixed rather than letting Claude decide the steps
   - Why Claude is called once at the end rather than throughout the pipeline
   - Why the system prompt instructs Claude to return JSON only
   - Why there is a fallback if JSON parsing fails
   - What each investigation step contributes to the final report

---

## Module 4: app/agent.py

Add the following:

1. A module-level docstring explaining:
   - This module implements the autonomous tool use pattern (Layer 7)
   - Unlike the investigator, Claude decides which tools to call and in what order
   - This pattern trades predictability for flexibility in open-ended analysis

2. A docstring on run_agent() explaining the tool use loop and termination conditions.

3. Inline comments explaining:
   - Why there is a maximum iteration limit
   - Why the system prompt instructs Claude not to ask follow-up questions
   - How the tool use loop works: Claude requests a tool, your code executes it,
     results are fed back into the next Claude call
   - Why this pattern is more expensive than the investigator pattern
   - When you would choose this pattern over the investigator pattern

---

## Expected file changes summary

- app/devrev_client.py: docstrings and inline comments added
- app/ci_webhook.py: docstrings and inline comments added
- app/investigator.py: docstrings and inline comments added
- app/agent.py: docstrings and inline comments added
