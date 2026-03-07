# Functional Tests

This directory contains functional tests that verify AI system behavior at two levels.

## Structural tests (test_structural.py)

Verify response shapes and infrastructure behavior using mocked Claude API calls.
Run without a live Docker stack.

```bash
pytest tests/functional/test_structural.py -v
```

## Behavioral tests (test_behavioral.py)

Verify that the AI system does what it claims to do using real Claude API calls and real ChromaDB queries.
Require a live Docker stack and valid environment variables.

### Setup

1. Start the Docker stack: `docker compose up --build -d --wait`
2. Issue an API key: `curl -X POST http://localhost:8001/keys -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" -d '{"name": "functional"}'`
3. Export the key: `export API_KEY=your-key-here`

### Run

```bash
pytest tests/functional/test_behavioral.py -v -m behavioral
```

### Cost

Each behavioral test run makes approximately 3 to 5 Claude API calls using claude-sonnet-4-6 and claude-haiku-4-5-20251001. Estimated cost per full run is under $0.05.

## Run all functional tests

```bash
pytest tests/functional/ -v
```
