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
