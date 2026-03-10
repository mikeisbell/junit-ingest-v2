# INSTRUCTIONS_KNOWLEDGE_GRAPH.md

## Goal

Add a Neo4j knowledge graph layer to junit-ingest-v2 that maps test cases to features,
code modules, and bugs. Build two new capabilities on top of the graph:

1. Impact-driven test selection: given a list of changed code modules, return the
   prioritized test cases that should run based on graph traversal.
2. Escaped defect gap analysis: given a bug ID, return a coverage analysis showing
   which test cases cover the affected feature, whether they ran recently, and
   whether gaps exist.

Extend the investigator pipeline to include a graph traversal step before Claude
synthesis so Claude reasons over both semantic context and relational context.

---

## Constraints

- Do not modify any existing endpoints.
- Do not modify any existing test files.
- Do not modify app/investigator.py logic except to add one new graph traversal step
  after the search_similar step.
- The graph layer must be fail-open: if Neo4j is unavailable, all existing endpoints
  continue to work normally. Only the new graph endpoints return an error.
- Add neo4j to requirements.txt. The correct package is: neo4j
- All new code must have docstrings and inline comments explaining the why.

---

## New dependency

Add to requirements.txt:
```
neo4j
```

---

## New environment variables

Add to docker-compose.yml under the api service environment block:
```
NEO4J_URI: bolt://neo4j:7687
NEO4J_USER: neo4j
NEO4J_PASSWORD: ${NEO4J_PASSWORD:-devrev_demo}
```

---

## Step 1: Add Neo4j to docker-compose.yml

Add a neo4j service:

```yaml
neo4j:
  image: neo4j:5-community
  environment:
    NEO4J_AUTH: neo4j/${NEO4J_PASSWORD:-devrev_demo}
    NEO4J_PLUGINS: '[]'
    NEO4J_dbms_memory_heap_initial__size: 256m
    NEO4J_dbms_memory_heap_max__size: 512m
  ports:
    - "7474:7474"
    - "7687:7687"
  volumes:
    - neo4j_data:/data
  healthcheck:
    test: ["CMD", "neo4j", "status"]
    interval: 10s
    timeout: 5s
    retries: 10
```

Add neo4j_data to the volumes block at the bottom of docker-compose.yml.

Add neo4j to the depends_on block of the api service with condition: service_healthy.
Add neo4j to the depends_on block of the celery_worker service with condition: service_healthy.

---

## Step 2: Create app/graph_store.py

This module manages all Neo4j interactions.

### Node types

- TestCase: {name: str, suite_name: str, status: str}
- TestSuite: {name: str, total_tests: int, total_failures: int}
- Feature: {name: str, description: str}
- CodeModule: {name: str, path: str}
- Bug: {id: str, title: str, severity: str, escaped: bool}

### Relationship types

- (TestCase)-[:COVERS]->(Feature)
- (Feature)-[:IMPLEMENTED_IN]->(CodeModule)
- (Bug)-[:AFFECTS]->(Feature)
- (TestCase)-[:REPRODUCES]->(Bug)
- (TestSuite)-[:CONTAINS]->(TestCase)

### Functions to implement

**get_driver() -> Driver**
Returns a Neo4j driver instance. Read NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD from
environment. Use neo4j.GraphDatabase.driver(). Log a warning and return None if
connection fails. This enables fail-open behavior.

**init_graph(driver) -> None**
Creates uniqueness constraints on TestCase.name, Feature.name, CodeModule.name,
Bug.id. Run on startup. Use CREATE CONSTRAINT IF NOT EXISTS syntax.

**ingest_suite_to_graph(driver, suite: TestSuiteResult, feature_map: dict) -> None**
Ingests a TestSuiteResult into the graph.
- Creates a TestSuite node
- Creates a TestCase node for each test case
- Creates CONTAINS relationships from suite to each test case
- For each test case, looks up feature_map[test_case.name] to find the feature name
  and creates a COVERS relationship if a mapping exists
- Use MERGE not CREATE to avoid duplicates
- If driver is None, log a warning and return without raising

**get_tests_for_modules(driver, module_names: list[str]) -> list[dict]**
Given a list of changed code module names, returns test cases that cover features
implemented in those modules. Traversal path:
(CodeModule)<-[:IMPLEMENTED_IN]-(Feature)<-[:COVERS]-(TestCase)
Returns a list of dicts with keys: test_name, feature_name, module_name, priority.
Priority is "high" if the test case's suite had failures in the last ingestion,
"normal" otherwise.
If driver is None, return empty list.

**get_gap_analysis(driver, bug_id: str) -> dict**
Given a bug ID, returns coverage analysis.
Traversal path: (Bug)-[:AFFECTS]->(Feature)<-[:COVERS]-(TestCase)
Returns:
- bug: {id, title, severity, escaped}
- affected_feature: {name, description}
- covering_tests: list of {name, suite_name, status}
- gap_assessment: "covered" if at least one passing test covers the feature,
  "gap_detected" if no test covers the feature,
  "coverage_unreliable" if tests exist but all have status "failed" or "error"
If bug_id not found, return {"error": "bug not found"}.
If driver is None, return {"error": "graph unavailable"}.

**seed_graph(driver) -> None**
Seeds the graph with synthetic but realistic data representing a typical
infotainment or SaaS product.

Create these CodeModule nodes:
- {name: "payment_processor", path: "app/payments/processor.py"}
- {name: "user_auth", path: "app/auth/user.py"}
- {name: "cart_service", path: "app/cart/service.py"}
- {name: "order_service", path: "app/orders/service.py"}
- {name: "notification_service", path: "app/notifications/service.py"}
- {name: "api_gateway", path: "app/gateway/router.py"}

Create these Feature nodes:
- {name: "checkout_flow", description: "End-to-end purchase checkout"}
- {name: "user_profile", description: "User account and profile management"}
- {name: "shopping_cart", description: "Cart add, remove, and update"}
- {name: "order_processing", description: "Order creation and fulfillment"}
- {name: "payment_gateway", description: "Payment processing and validation"}

Create these Feature IMPLEMENTED_IN CodeModule relationships:
- checkout_flow -> payment_processor
- checkout_flow -> cart_service
- checkout_flow -> order_service
- user_profile -> user_auth
- shopping_cart -> cart_service
- order_processing -> order_service
- order_processing -> api_gateway
- payment_gateway -> payment_processor

Create these Bug nodes:
- {id: "BUG-001", title: "Checkout fails when cart has more than 10 items",
   severity: "high", escaped: true}
- {id: "BUG-002", title: "User profile email not updated after change",
   severity: "medium", escaped: true}
- {id: "BUG-003", title: "Payment gateway timeout under load",
   severity: "high", escaped: false}
- {id: "BUG-004", title: "Order status not updated after payment",
   severity: "medium", escaped: false}

Create these Bug AFFECTS Feature relationships:
- BUG-001 -> checkout_flow
- BUG-001 -> shopping_cart
- BUG-002 -> user_profile
- BUG-003 -> payment_gateway
- BUG-004 -> order_processing

Create this feature_map dict that maps test case names from sample_rich.xml to features.
This dict is also used by ingest_suite_to_graph:
```python
FEATURE_MAP = {
    "test_user_login": "user_profile",
    "test_user_profile_update": "user_profile",
    "test_user_age_validation": "user_profile",
    "test_add_to_cart": "shopping_cart",
    "test_cart_item_quantity": "shopping_cart",
    "test_checkout_flow": "checkout_flow",
    "test_checkout_with_promo": "checkout_flow",
    "test_multiplication_fails": "order_processing",
    "test_order_processing": "order_processing",
    "test_payment_gateway": "payment_gateway",
    "test_payment_gateway_timeout": "payment_gateway",
    "test_legacy_payment_flow": "payment_gateway",
}
```

Export FEATURE_MAP from this module so other modules can import it.

Use MERGE not CREATE for all seed operations to make seeding idempotent.

---

## Step 3: Update app/main.py lifespan function

In the lifespan context manager, after table creation:
1. Import get_driver, init_graph, seed_graph from app.graph_store
2. Call driver = get_driver()
3. If driver is not None, call init_graph(driver) then seed_graph(driver)
4. Store driver on app.state: app.state.neo4j_driver = driver
5. On shutdown, if driver is not None, call driver.close()

---

## Step 4: Update app/main.py POST /results endpoint

After db.commit() and db.refresh(db_result) in POST /results:
1. Import FEATURE_MAP and ingest_suite_to_graph from app.graph_store
2. Call ingest_suite_to_graph(request.app.state.neo4j_driver, result, FEATURE_MAP)
   where result is the parsed TestSuiteResult Pydantic object
3. Wrap in try/except: log a warning on failure, do not raise

To access app.state in a FastAPI endpoint, add Request as a parameter:
```python
async def ingest_results(request: Request, file: UploadFile, db: Session = Depends(get_db)):
```

---

## Step 5: Update app/investigator.py

Add a graph traversal step between search_similar and get_stats.

The new step is named "graph_context" and must:
1. Accept the driver from app.state via a new optional parameter:
   def investigate_suite(suite_id: int, db: Session, driver=None) -> dict:
2. If driver is None, skip the step and set graph_context = {}
3. If driver is available:
   a. Get the list of failing test case names from the suite
   b. For each failing test, query which feature it covers using a simple Cypher query:
      MATCH (t:TestCase {name: $name})-[:COVERS]->(f:Feature) RETURN f.name
   c. For each feature found, get related bugs:
      MATCH (b:Bug)-[:AFFECTS]->(f:Feature {name: $feature}) RETURN b.id, b.title, b.severity
   d. Build graph_context dict:
      {feature_name: {bugs: [{id, title, severity}]}}
4. Log investigation_step with step="graph_context" and feature_count
5. Pass graph_context into the Claude prompt as an additional section:
   "Graph Context: {json.dumps(graph_context, indent=2)}"
   Add this after the similar failures section in the prompt

---

## Step 6: Update app/ci_webhook.py

Update the call to investigate_suite to pass the driver:
```python
report_outer = investigate_suite(db_suite.id, db, driver=request.app.state.neo4j_driver)
```

Add Request as a parameter to process_ci_webhook:
```python
def process_ci_webhook(suite: TestSuiteResult, db: Session, driver=None) -> dict:
```

Update POST /webhook/ci in main.py to pass the driver:
```python
result = process_ci_webhook(parsed_suite, db, driver=request.app.state.neo4j_driver)
```

---

## Step 7: Add GET /graph/churn endpoint to app/main.py

```
POST /graph/churn
```

Request body:
```json
{"modules": ["payment_processor", "cart_service"]}
```

This endpoint:
1. Requires authentication (apply require_api_key dependency)
2. Calls get_tests_for_modules(request.app.state.neo4j_driver, modules)
3. Returns:
```json
{
  "changed_modules": ["payment_processor", "cart_service"],
  "recommended_tests": [
    {"test_name": "test_checkout_flow", "feature_name": "checkout_flow",
     "module_name": "payment_processor", "priority": "high"}
  ],
  "total_recommended": 3
}
```
4. If graph is unavailable return HTTP 503 with message "graph unavailable"

Create a Pydantic request model:
```python
class ChurnRequest(BaseModel):
    modules: list[str]
```

---

## Step 8: Add GET /graph/gaps/{bug_id} endpoint to app/main.py

```
GET /graph/gaps/{bug_id}
```

This endpoint:
1. Requires authentication (apply require_api_key dependency)
2. Calls get_gap_analysis(request.app.state.neo4j_driver, bug_id)
3. Returns the dict from get_gap_analysis directly
4. If the result contains "error": "bug not found" return HTTP 404
5. If the result contains "error": "graph unavailable" return HTTP 503

---

## Step 9: Update GET /health endpoint

Add a neo4j check to the health endpoint alongside the existing postgres and chromadb checks.

Check neo4j by running: RETURN 1 using the driver session.
Add to the dependencies dict:
```json
"neo4j": {"status": "ok"}
```
or
```json
"neo4j": {"status": "error", "detail": "<error message>"}
```
Set overall status to "degraded" if neo4j check fails, consistent with existing behavior.

---

## Step 10: Create tests/test_graph_store.py

Unit tests for app/graph_store.py. Use mocked Neo4j driver throughout.
Do not require a live Neo4j instance.

Tests must cover:

1. test_get_driver_returns_none_on_failure: Patch GraphDatabase.driver to raise an
   exception. Assert get_driver() returns None without raising.

2. test_ingest_suite_skips_when_driver_none: Call ingest_suite_to_graph with
   driver=None and a valid TestSuiteResult. Assert no exception is raised.

3. test_get_tests_for_modules_returns_empty_when_driver_none: Call
   get_tests_for_modules with driver=None. Assert returns empty list.

4. test_get_gap_analysis_returns_error_when_driver_none: Call get_gap_analysis
   with driver=None. Assert returns {"error": "graph unavailable"}.

5. test_churn_endpoint_returns_503_when_graph_unavailable: Using TestClient,
   POST to /graph/churn with valid auth and mock get_tests_for_modules to simulate
   driver=None behavior. Assert 503 response.

6. test_gaps_endpoint_returns_404_for_unknown_bug: Using TestClient, GET
   /graph/gaps/UNKNOWN-999 with valid auth and mock get_gap_analysis to return
   {"error": "bug not found"}. Assert 404 response.

---

## Expected file changes summary

- requirements.txt: add neo4j
- docker-compose.yml: add neo4j service, neo4j_data volume, env vars, depends_on updates
- app/graph_store.py: new file
- app/main.py: lifespan update, POST /results update, new endpoints, health check update
- app/investigator.py: add graph_context step and driver parameter
- app/ci_webhook.py: pass driver to investigate_suite
- tests/test_graph_store.py: new file
