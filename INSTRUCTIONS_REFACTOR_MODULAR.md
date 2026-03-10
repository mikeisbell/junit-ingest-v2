# INSTRUCTIONS_REFACTOR_MODULAR.md

## Goal

Refactor the project to enforce a clean separation between tool code, test data, and
demo data. Split app/graph_store.py into a proper Python subpackage with
single-responsibility modules. Move all hardcoded demo and test data out of application
code into the appropriate folders.

This refactor must not change any existing behavior. All existing endpoints must
continue to work. All existing tests must continue to pass after updates.

---

## Constraints

- Do not change any endpoint signatures, request formats, or response formats.
- Do not change any existing business logic in any module.
- Do not add any new dependencies.
- All imports throughout the codebase must be updated to reflect the new module
  structure.
- After this refactor, app/ must contain zero hardcoded feature maps, seed data,
  or XML content.

---

## Target directory structure

```
junit-ingest-v2/
├── app/
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── driver.py
│   │   ├── schema.py
│   │   ├── ingest.py
│   │   ├── queries.py
│   │   └── seed.py
│   ├── integrations/
│   │   ├── __init__.py
│   │   └── devrev.py
│   ├── __init__.py
│   ├── agent.py
│   ├── agent_tasks.py
│   ├── agent_tools.py
│   ├── auth.py
│   ├── cache.py
│   ├── celery_app.py
│   ├── ci_webhook.py
│   ├── database.py
│   ├── db_models.py
│   ├── investigator.py
│   ├── logging_config.py
│   ├── main.py
│   ├── middleware.py
│   ├── models.py
│   ├── parser.py
│   ├── rag.py
│   ├── rate_limiter.py
│   ├── tasks.py
│   └── vector_store.py
├── tests/
│   ├── fixtures/
│   │   ├── test.xml
│   │   ├── feature_map.py
│   │   └── seed_data.py
│   ├── eval/
│   │   └── eval_retrieval.py
│   ├── functional/
│   │   ├── test_structural.py
│   │   └── test_behavioral.py
│   ├── integration/
│   │   └── test_integration.py
│   ├── conftest.py
│   ├── test_agent.py
│   ├── test_auth.py
│   ├── test_ci_webhook.py
│   ├── test_devrev_client.py
│   ├── test_graph_store.py
│   ├── test_ingest.py
│   └── test_investigator.py
├── demo/
│   ├── README.md
│   ├── seed.py
│   ├── ingest.py
│   └── data/
│       ├── feature_map.json
│       ├── seed_data.json
│       └── demo.xml
```

---

## Step 1: Create app/graph/ subpackage

Create the directory app/graph/ and split app/graph_store.py into five modules.
Delete app/graph_store.py after all imports are updated.

### app/graph/__init__.py

Export the public API so callers can use:
```python
from app.graph import get_driver, init_graph, ingest_suite_to_graph
from app.graph import get_tests_for_modules, get_gap_analysis, seed_graph
```

Implement by importing from the submodules:
```python
from .driver import get_driver
from .schema import init_graph
from .ingest import ingest_suite_to_graph
from .queries import get_tests_for_modules, get_gap_analysis
from .seed import seed_graph
```

Do NOT export FEATURE_MAP from app/graph/__init__.py or any app/graph/ module.
FEATURE_MAP does not belong in application code.

### app/graph/driver.py

Contains only get_driver().
Reads NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD from environment.
Returns a connected neo4j.Driver or None on failure.
Contains the module docstring explaining connection management and fail-open behavior.

### app/graph/schema.py

Contains only init_graph(driver).
Creates uniqueness constraints on TestCase.name, Feature.name, CodeModule.name, Bug.id.
Contains the module docstring explaining why constraints are created at startup.

### app/graph/ingest.py

Contains only ingest_suite_to_graph(driver, suite, feature_map).
The feature_map parameter is required. The function does not have a default or
fallback feature map. If feature_map is empty, no COVERS relationships are created.
Contains the module docstring explaining the ingestion pattern and MERGE semantics.

### app/graph/queries.py

Contains get_tests_for_modules(driver, module_names) and get_gap_analysis(driver, bug_id).
Contains the module docstring explaining the two graph traversal use cases.

### app/graph/seed.py

Contains only seed_graph(driver, seed_data).
The seed_data parameter is a dict with this structure:
```python
{
    "modules": [{"name": str, "path": str}],
    "features": [{"name": str, "description": str}],
    "feature_module_edges": [{"feature": str, "module": str}],
    "bugs": [{"id": str, "title": str, "severity": str, "escaped": bool}],
    "bug_feature_edges": [{"bug_id": str, "feature": str}]
}
```
The function uses MERGE for all operations so it is idempotent.
It does not hardcode any nodes, relationships, or names.
Contains the module docstring explaining why seed data is external.

---

## Step 2: Create app/integrations/ subpackage

Create the directory app/integrations/ and move app/devrev_client.py into it as
app/integrations/devrev.py.

### app/integrations/__init__.py

Empty file. Makes integrations a proper Python subpackage.
Add a module docstring:
```
Integration modules for external tools and platforms.
Each integration is a self-contained module that can be added or replaced
without affecting the core tool. Current integrations: DevRev.
```

### app/integrations/devrev.py

Move all content from app/devrev_client.py into this file verbatim.
Do not change any logic, class names, function names, or behavior.
Update the module docstring to reflect the new location:
- Old: "This module is the single integration point between junit-ingest-v2 and the DevRev API"
- New: "DevRev integration for junit-ingest-v2. One of potentially many integrations
  in app/integrations/. To integrate with a different issue tracker, add a new module
  alongside this one following the same DevRevIssue dataclass and create_issue() pattern."

### Update all imports

Replace all occurrences of:
```python
from app.devrev_client import ...
from .devrev_client import ...
```

With:
```python
from app.integrations.devrev import ...
from .integrations.devrev import ...
```

Affected files: app/main.py, app/ci_webhook.py, tests/test_devrev_client.py,
tests/test_ci_webhook.py.

### Delete app/devrev_client.py

Delete app/devrev_client.py after all imports are updated and tests pass.

---

## Step 3: Create tests/fixtures/

### tests/fixtures/test.xml

Create tests/fixtures/test.xml. This is the single XML fixture used by all automated
tests. It must have enough variety to exercise the parser, database models, embeddings,
and graph ingestion. Use this content:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="FixtureTestSuite" tests="8" failures="2" errors="1" skipped="1" time="3.456">
  <testcase name="test_user_login" classname="tests.auth" time="0.123"/>
  <testcase name="test_add_to_cart" classname="tests.cart" time="0.234"/>
  <testcase name="test_checkout_flow" classname="tests.checkout" time="0.345"/>
  <testcase name="test_payment_gateway" classname="tests.payments" time="0.456">
    <failure message="AssertionError: expected 200, got 422">
AssertionError: Payment gateway returned unexpected status.
Expected: 200
Actual: 422
Request: POST /api/v1/payments/process
    </failure>
  </testcase>
  <testcase name="test_order_processing" classname="tests.orders" time="0.567">
    <failure message="NullPointerException: order object was None">
NullPointerException: order object was None after create_order() returned success.
Possible race condition in order_service.create() under concurrent load.
    </failure>
  </testcase>
  <testcase name="test_cart_concurrent_updates" classname="tests.cart" time="1.234">
    <error message="ConnectionError: database connection pool exhausted">
ConnectionError: database connection pool exhausted
Max pool size: 10, Active: 10, Waiting: 23
    </error>
  </testcase>
  <testcase name="test_update_cart_quantity" classname="tests.cart" time="0.189"/>
  <testcase name="test_legacy_payment_flow" classname="tests.payments" time="0.112">
    <skipped message="Legacy payment flow deprecated, skipping until migration complete"/>
  </testcase>
</testsuite>
```

### tests/fixtures/feature_map.py

Contains the feature map used by graph-related tests as a Python dict constant.
This is test data, not application code.

```python
# Feature map fixture for graph ingestion tests.
# Maps test case names in tests/fixtures/test.xml to feature names
# that match the seed_data fixture below.
FIXTURE_FEATURE_MAP = {
    "test_user_login": "user_profile",
    "test_add_to_cart": "shopping_cart",
    "test_checkout_flow": "checkout_flow",
    "test_payment_gateway": "payment_gateway",
    "test_order_processing": "order_processing",
    "test_cart_concurrent_updates": "shopping_cart",
    "test_update_cart_quantity": "shopping_cart",
    "test_legacy_payment_flow": "payment_gateway",
}
```

### tests/fixtures/seed_data.py

Contains the graph seed data used by graph-related tests as a Python dict constant.
This is test data, not application code.

```python
# Minimal graph seed data for unit and integration tests.
# Uses a small realistic dataset that exercises all node types and relationships.
FIXTURE_SEED_DATA = {
    "modules": [
        {"name": "payment_processor", "path": "app/payments/processor.py"},
        {"name": "cart_service", "path": "app/cart/service.py"},
        {"name": "order_service", "path": "app/orders/service.py"},
        {"name": "user_auth", "path": "app/auth/user.py"},
    ],
    "features": [
        {"name": "checkout_flow", "description": "End-to-end purchase checkout"},
        {"name": "user_profile", "description": "User account and profile management"},
        {"name": "shopping_cart", "description": "Cart add, remove, and update"},
        {"name": "order_processing", "description": "Order creation and fulfillment"},
        {"name": "payment_gateway", "description": "Payment processing and validation"},
    ],
    "feature_module_edges": [
        {"feature": "checkout_flow", "module": "payment_processor"},
        {"feature": "checkout_flow", "module": "cart_service"},
        {"feature": "shopping_cart", "module": "cart_service"},
        {"feature": "order_processing", "module": "order_service"},
        {"feature": "payment_gateway", "module": "payment_processor"},
        {"feature": "user_profile", "module": "user_auth"},
    ],
    "bugs": [
        {"id": "BUG-001", "title": "Checkout fails when cart has more than 10 items",
         "severity": "high", "escaped": True},
        {"id": "BUG-002", "title": "User profile email not updated after change",
         "severity": "medium", "escaped": True},
    ],
    "bug_feature_edges": [
        {"bug_id": "BUG-001", "feature": "checkout_flow"},
        {"bug_id": "BUG-001", "feature": "shopping_cart"},
        {"bug_id": "BUG-002", "feature": "user_profile"},
    ],
}
```

---

## Step 4: Create demo/ folder

### demo/data/feature_map.json

```json
{
  "test_user_login": "user_profile",
  "test_user_profile_update": "user_profile",
  "test_user_age_validation": "user_profile",
  "test_add_to_cart": "shopping_cart",
  "test_add_to_cart_duplicate_item": "shopping_cart",
  "test_add_to_cart_max_quantity": "shopping_cart",
  "test_cart_item_quantity": "shopping_cart",
  "test_remove_from_cart": "shopping_cart",
  "test_remove_nonexistent_item": "shopping_cart",
  "test_update_cart_quantity": "shopping_cart",
  "test_update_cart_quantity_zero": "shopping_cart",
  "test_clear_cart": "shopping_cart",
  "test_cart_persistence_across_sessions": "shopping_cart",
  "test_apply_promo_code": "checkout_flow",
  "test_apply_invalid_promo_code": "checkout_flow",
  "test_apply_expired_promo_code": "checkout_flow",
  "test_cart_database_write": "shopping_cart",
  "test_cart_database_read": "shopping_cart",
  "test_cart_concurrent_updates": "shopping_cart",
  "test_cart_database_timeout": "shopping_cart",
  "test_cart_to_checkout_handoff": "checkout_flow",
  "test_cart_large_order": "checkout_flow",
  "test_legacy_cart_migration": "shopping_cart",
  "test_checkout_flow": "checkout_flow",
  "test_checkout_with_promo": "checkout_flow",
  "test_multiplication_fails": "order_processing",
  "test_order_processing": "order_processing",
  "test_payment_gateway": "payment_gateway",
  "test_payment_gateway_timeout": "payment_gateway",
  "test_legacy_payment_flow": "payment_gateway"
}
```

### demo/data/seed_data.json

```json
{
  "modules": [
    {"name": "payment_processor", "path": "app/payments/processor.py"},
    {"name": "user_auth", "path": "app/auth/user.py"},
    {"name": "cart_service", "path": "app/cart/service.py"},
    {"name": "order_service", "path": "app/orders/service.py"},
    {"name": "notification_service", "path": "app/notifications/service.py"},
    {"name": "api_gateway", "path": "app/gateway/router.py"}
  ],
  "features": [
    {"name": "checkout_flow", "description": "End-to-end purchase checkout"},
    {"name": "user_profile", "description": "User account and profile management"},
    {"name": "shopping_cart", "description": "Cart add, remove, and update"},
    {"name": "order_processing", "description": "Order creation and fulfillment"},
    {"name": "payment_gateway", "description": "Payment processing and validation"}
  ],
  "feature_module_edges": [
    {"feature": "checkout_flow", "module": "payment_processor"},
    {"feature": "checkout_flow", "module": "cart_service"},
    {"feature": "checkout_flow", "module": "order_service"},
    {"feature": "user_profile", "module": "user_auth"},
    {"feature": "shopping_cart", "module": "cart_service"},
    {"feature": "order_processing", "module": "order_service"},
    {"feature": "order_processing", "module": "api_gateway"},
    {"feature": "payment_gateway", "module": "payment_processor"}
  ],
  "bugs": [
    {"id": "BUG-001", "title": "Checkout fails when cart has more than 10 items",
     "severity": "high", "escaped": true},
    {"id": "BUG-002", "title": "User profile email not updated after change",
     "severity": "medium", "escaped": true},
    {"id": "BUG-003", "title": "Payment gateway timeout under load",
     "severity": "high", "escaped": false},
    {"id": "BUG-004", "title": "Order status not updated after payment",
     "severity": "medium", "escaped": false}
  ],
  "bug_feature_edges": [
    {"bug_id": "BUG-001", "feature": "checkout_flow"},
    {"bug_id": "BUG-001", "feature": "shopping_cart"},
    {"bug_id": "BUG-002", "feature": "user_profile"},
    {"bug_id": "BUG-003", "feature": "payment_gateway"},
    {"bug_id": "BUG-004", "feature": "order_processing"}
  ]
}
```

### demo/data/demo.xml

Copy the full content of the sample_cart.xml file created in the previous layer.
This is the demo ingestion file. Rename it to demo.xml in this location.

### demo/seed.py

Standalone script. Run this once to seed the demo graph.

```python
#!/usr/bin/env python3
"""Seed the Neo4j knowledge graph with demo data.

Run this script once after starting the Docker stack to populate the graph
with realistic nodes and relationships for the demo environment.

Usage:
    python demo/seed.py

Environment variables required:
    NEO4J_URI      (default: bolt://localhost:7687)
    NEO4J_USER     (default: neo4j)
    NEO4J_PASSWORD (default: devrev_demo)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.graph import get_driver, init_graph, seed_graph

SEED_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "seed_data.json")


def main():
    with open(SEED_DATA_PATH) as f:
        seed_data = json.load(f)

    driver = get_driver()
    if driver is None:
        print("ERROR: Could not connect to Neo4j. Is the stack running?")
        sys.exit(1)

    init_graph(driver)
    seed_graph(driver, seed_data)
    driver.close()
    print("Demo graph seeded successfully.")


if __name__ == "__main__":
    main()
```

### demo/ingest.py

Standalone script. Run this to ingest demo.xml via the live API.

```python
#!/usr/bin/env python3
"""Ingest demo test results into the running junit-ingest-v2 service.

Run this script after seeding the graph to populate the service with
realistic test failure data for the demo environment.

Usage:
    API_KEY=your-key python demo/ingest.py

Environment variables required:
    API_KEY        Bearer token issued via POST /keys
    SERVICE_URL    (default: http://localhost:8001)
"""
import os
import sys
import urllib.request

SERVICE_URL = os.getenv("SERVICE_URL", "http://localhost:8001")
API_KEY = os.getenv("API_KEY", "")
DEMO_XML_PATH = os.path.join(os.path.dirname(__file__), "data", "demo.xml")


def main():
    if not API_KEY:
        print("ERROR: API_KEY environment variable not set.")
        sys.exit(1)

    with open(DEMO_XML_PATH, "rb") as f:
        xml_content = f.read()

    boundary = "----DemoIngestBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="demo.xml"\r\n'
        f"Content-Type: application/xml\r\n\r\n"
    ).encode() + xml_content + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{SERVICE_URL}/webhook/ci",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )

    with urllib.request.urlopen(req) as resp:
        print(f"Status: {resp.status}")
        print(resp.read().decode())


if __name__ == "__main__":
    main()
```

### demo/README.md

```markdown
# Demo Setup

This directory contains everything needed to run a live demo of junit-ingest-v2.

## Prerequisites

1. Start the stack: `docker compose up -d --wait`
2. Issue an API key:
   ```bash
   export API_KEY=$(curl -s -X POST http://localhost:8001/keys \
     -H "X-Admin-Token: $ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name": "demo"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['key'])")
   ```

## Seed the graph

```bash
python demo/seed.py
```

## Ingest demo test results

```bash
API_KEY=$API_KEY python demo/ingest.py
```

## Demo endpoints

```bash
# Semantic search for failures
curl "http://localhost:8001/search?q=cart+persistence+failure" \
  -H "Authorization: Bearer $API_KEY"

# Impact-driven test selection: which tests to run when cart_service changes
curl -X POST http://localhost:8001/graph/churn \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"modules": ["cart_service"]}'

# Gap analysis: coverage for BUG-001
curl http://localhost:8001/graph/gaps/BUG-001 \
  -H "Authorization: Bearer $API_KEY"

# AI investigation of the ingested suite
curl -X POST http://localhost:8001/investigate/1 \
  -H "Authorization: Bearer $API_KEY"
```

## Neo4j browser

Open http://localhost:7474 (user: neo4j, password: devrev_demo)

Visualize the full graph:
```cypher
MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 50
```

Churn query for cart_service:
```cypher
MATCH (m:CodeModule {name: "cart_service"})<-[:IMPLEMENTED_IN]-(f:Feature)<-[:COVERS]-(t:TestCase)
RETURN t.name, f.name, m.name
```

Gap analysis for BUG-001:
```cypher
MATCH (b:Bug {id: "BUG-001"})-[:AFFECTS]->(f:Feature)<-[:COVERS]-(t:TestCase)
RETURN b.title, f.name, t.name, t.status
```
```

---

## Step 5: Update app/main.py lifespan

Update the lifespan function to load seed data from demo/data/seed_data.json
at startup if the file exists, and pass it to seed_graph.

```python
import json

DEMO_SEED_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "demo", "data", "seed_data.json"
)

# In lifespan, after init_graph:
if os.path.exists(DEMO_SEED_PATH):
    with open(DEMO_SEED_PATH) as f:
        seed_data = json.load(f)
    seed_graph(driver, seed_data)
```

This keeps seeding automatic for the demo environment while keeping seed data
out of application code.

---

## Step 6: Update app/main.py POST /results endpoint

The feature map is no longer imported from app.graph. Instead, load it from
demo/data/feature_map.json at startup and store it on app.state:

```python
DEMO_FEATURE_MAP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "demo", "data", "feature_map.json"
)

# In lifespan:
if os.path.exists(DEMO_FEATURE_MAP_PATH):
    with open(DEMO_FEATURE_MAP_PATH) as f:
        app.state.feature_map = json.load(f)
else:
    app.state.feature_map = {}
```

In POST /results, replace the FEATURE_MAP import with:
```python
ingest_suite_to_graph(
    request.app.state.neo4j_driver,
    result,
    request.app.state.feature_map
)
```

---

## Step 7: Update all imports across the codebase

Replace all occurrences of:
```python
from app.graph_store import ...
from .graph_store import ...
```

With:
```python
from app.graph import ...
from .graph import ...
```

Affected files: app/main.py, app/investigator.py, app/ci_webhook.py,
tests/test_graph_store.py, and any other file that imported from graph_store.

---

## Step 8: Update all test files that reference sample.xml or sample_rich.xml

Search all files in tests/ for references to sample.xml and sample_rich.xml.
Replace all such references with tests/fixtures/test.xml.

Files likely affected: tests/conftest.py, tests/test_ingest.py,
tests/functional/test_structural.py, tests/functional/test_behavioral.py,
tests/integration/test_integration.py, tests/eval/eval_retrieval.py.

---

## Step 9: Update tests/test_graph_store.py

Update test_graph_store.py to import FIXTURE_FEATURE_MAP and FIXTURE_SEED_DATA
from tests/fixtures/feature_map.py and tests/fixtures/seed_data.py respectively.
Remove any hardcoded feature maps or seed data from the test file itself.

---

## Step 10: Delete obsolete files

Delete these files after all references are updated and tests pass:
- app/graph_store.py
- tests/sample.xml
- tests/sample_rich.xml
- tests/sample_cart.xml (if it exists)

---

## Step 11: Verify

Run pytest and confirm all tests pass:
```bash
pytest --ignore=tests/integration --ignore=tests/functional -v
```

Confirm no remaining references to graph_store, sample.xml, or sample_rich.xml:
```bash
grep -r "graph_store\|devrev_client\|sample\.xml\|sample_rich" app/ tests/ --include="*.py"
```

Both commands must return clean results before this refactor is considered complete.

---

## Expected file changes summary

New files:
- app/graph/__init__.py
- app/graph/driver.py
- app/graph/schema.py
- app/graph/ingest.py
- app/graph/queries.py
- app/graph/seed.py
- app/integrations/__init__.py
- app/integrations/devrev.py
- tests/fixtures/test.xml
- tests/fixtures/feature_map.py
- tests/fixtures/seed_data.py
- demo/README.md
- demo/seed.py
- demo/ingest.py
- demo/data/feature_map.json
- demo/data/seed_data.json
- demo/data/demo.xml

Modified files:
- app/main.py
- app/investigator.py
- app/ci_webhook.py
- tests/test_graph_store.py
- tests/conftest.py
- tests/test_ingest.py
- tests/functional/test_structural.py
- tests/functional/test_behavioral.py
- tests/integration/test_integration.py

Deleted files:
- app/graph_store.py
- app/devrev_client.py
- tests/sample.xml
- tests/sample_rich.xml
- tests/sample_cart.xml
