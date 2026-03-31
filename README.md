# junit-ingest-v2 — AI Test Pipeline Demo

An AI-powered test pipeline that demonstrates impact-driven test selection,
automated failure analysis, and bug lifecycle management. Built as a hands-on
demonstration of AI-assisted engineering using Claude Sonnet via GitHub Copilot
agents in VS Code.

Each layer of this service was built by writing a natural language
`INSTRUCTIONS_*.md` file and handing it to a Copilot agent for implementation.

---

## What It Does

The pipeline implements a full CI/CD quality gate flow:

1. Developer opens an MR. `POST /webhook/premerge` selects tests by traversing
   the Neo4j knowledge graph to find test cases covering the changed modules,
   appends all P0 regression tests, simulates execution, and returns a merge
   recommendation.

2. If tests fail, the developer fixes the code and re-submits. When all tests
   pass, the MR is approved for merge.

3. After merge, a build triggers the full regression suite. `POST
   /webhook/analyze` receives the JUnit XML results, runs AI-powered failure
   analysis via Claude, creates or links bugs in the bug tracker, and promotes
   resolved bugs to Verified when their covering tests pass.

---

## Architecture

```
app/                        FastAPI pipeline service
  main.py                   API entry point, health check, all endpoints
  premerge_webhook.py       POST /webhook/premerge and POST /webhook/analyze
  ci_webhook.py             POST /webhook/ci (original ingestion flow)
  investigator.py           Deterministic 5-step AI analysis pipeline
  agent.py                  Autonomous tool-use agent (agentic pattern)
  graph/                    Neo4j knowledge graph: test selection, gap analysis
  integrations/devrev.py    DevRev issue creation (mock or live)

bug_tracker/                Separate module simulating an external bug tracker
  database.py               Own SQLAlchemy engine, own Postgres database
  models.py                 BugORM with JSON columns for build/test links
  tracker.py                Full CRUD: create, link, verify, reset

demo/
  cli.py                    Interactive demo CLI (see below)
  seed.py                   Seeds Neo4j graph and bug tracker
  data/                     Fixture files, seed data, demo JUnit XML
```

### Key architectural decisions

**The pipeline does not own the bug tracker.** `bug_tracker/` is a separate
module with its own Postgres database (`bug_tracker` db vs `junit_ingest` db).
In production this would be replaced by API calls to DevRev, Jira, or Linear.
The interface — `create_bug`, `find_bug_by_signature`, `set_bug_status` — stays
the same regardless of implementation.

**The LLM does not write Cypher.** Neo4j graph traversals use predetermined
parameterized queries written by developers. The LLM receives query results as
context and synthesizes a structured report. This keeps query execution
deterministic and costs predictable.

**Two investigator patterns.** `investigator.py` uses a fixed 4-step pipeline
where Python drives every data-gathering step and Claude is called once at the
end. `agent.py` uses autonomous tool selection. The deterministic pattern is
used for the CI webhook because consistency and cost matter more than
flexibility for a recurring analysis task.

---

## Stack

- **FastAPI** — API framework
- **PostgreSQL** — test results persistence (junit_ingest db) and bug tracker (bug_tracker db)
- **ChromaDB** — vector store for semantic failure search
- **Neo4j** — knowledge graph for impact-driven test selection and gap analysis
- **Redis** — caching and Celery broker
- **Celery** — async task queue for embeddings and investigations
- **Claude API** — AI failure analysis and synthesis
- **Docker Compose** — full local stack

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- An Anthropic API key
- An admin token of your choice (any string)

### Start the stack

```bash
# Set required environment variables
export ANTHROPIC_API_KEY=your_key_here
export ADMIN_TOKEN=your_admin_token_here

# Start all services
docker compose up -d --build

# Seed the Neo4j knowledge graph and bug tracker
docker compose exec api python demo/seed.py
```

### Verify health

```bash
curl -s http://localhost:8001/health | python -m json.tool
```

All four dependencies (postgres, chromadb, redis, neo4j) should show `"status": "ok"`.

---

## Demo CLI

The demo CLI injects fake artifacts into the live pipeline and shows real
responses. All state persists across sessions.

```bash
# Run any CLI command inside the container
docker compose exec \
  -e SERVICE_URL=http://localhost:8000 \
  -e ADMIN_TOKEN=$ADMIN_TOKEN \
  api python /app/demo/cli.py <command>
```

### Full demo flow

```bash
DEMO="docker compose exec -e SERVICE_URL=http://localhost:8000 -e ADMIN_TOKEN=$ADMIN_TOKEN api python /app/demo/cli.py"

# Check service health
$DEMO status

# See what the knowledge graph knows about cart_service
$DEMO graph show-tests --module cart_service

# MR submitted — pre-merge run with failures, merge blocked
$DEMO mr submit --mr-id MR-42 --author alice --modules cart_service payment_processor --outcome fail

# Developer fixes the code — pre-merge passes, merge approved
$DEMO mr submit --mr-id MR-42 --author alice --modules cart_service payment_processor --outcome pass

# MR committed — mark the bug it fixed as resolved
$DEMO bug update-status --bug-id BUG-001 --status resolved

# Regression build runs — failure analysis, bug linking, Verified promotion
$DEMO build submit --build-id build-47 --xml demo/data/demo.xml --triggered-by MR-42

# Final bug state — BUG-001, BUG-003, BUG-004 promoted to Verified
$DEMO bug list

# Reset for next demo run
$DEMO reset --confirm
```

### CLI reference

```
mr submit       --mr-id --author --modules [modules] --outcome pass|fail
mr list
mr show         --mr-id

build submit    --build-id --xml --triggered-by
build list
build show      --build-id

bug list
bug show        --bug-id
bug create      --title --severity --feature --signature
bug update-status  --bug-id --status open|resolved|verified
bug link        --bug-id --build --test-name

graph show-modules
graph show-features
graph show-tests    --module
graph gaps          --bug-id

status
reset           --confirm
```

---

## Running Tests

Tests run locally against the running Postgres instance.

```bash
# Unit and integration tests
BUG_TRACKER_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/bug_tracker \
  .venv/bin/python -m pytest --no-cov

# Bug tracker integration tests only
BUG_TRACKER_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/bug_tracker \
  .venv/bin/python -m pytest tests/test_bug_tracker.py -v -m integration
```

---

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /webhook/premerge | API key | Impact-driven pre-merge test selection and execution |
| POST | /webhook/analyze | API key | JUnit XML failure analysis and bug lifecycle management |
| POST | /webhook/ci | None | Original CI ingestion with DevRev issue creation |
| GET | /graph/gaps/{bug_id} | API key | Coverage gap analysis for a bug |
| POST | /graph/churn | API key | Test selection for changed modules |
| POST | /investigate/{suite_id} | API key | Async AI investigation of a test suite |
| POST | /agent | API key | Autonomous agentic failure analysis |
| GET | /search | API key | Semantic search over historical failures |
| GET | /results | API key | All ingested test suite results |
| POST | /keys | Admin token | Create API key |
| GET | /health | None | Service and dependency health check |

---

## How It Was Built

Every layer was built using the same AI-assisted workflow:

1. Write a natural language `INSTRUCTIONS_*.md` file describing what to build
2. Hand it to a Claude Sonnet agent in VS Code via GitHub Copilot
3. Review the generated code
4. Validate by running pytest and hitting endpoints

The `INSTRUCTIONS_*.md` files in the repo root are the source of truth for
each layer. Reading them shows exactly how the service was designed and built.

This mirrors the workflow used at Lucid Motors to generate 350+ pytest test
cases in one week — a 12-23x acceleration over manual test authoring.

---

## Demo Data

The demo uses a fictional e-commerce app with these features and modules:

**Features:** checkout_flow, shopping_cart, user_profile, order_processing, payment_gateway

**Modules:** cart_service, payment_processor, user_auth, order_service, notification_service, api_gateway

**Pre-seeded bugs:** BUG-001 through BUG-004 representing known issues in various states (open, resolved) before the demo MR is submitted.
