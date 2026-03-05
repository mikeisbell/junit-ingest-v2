# JUnit XML Ingestion Service

A FastAPI service that accepts JUnit XML file uploads, parses them, and returns structured test results.

## Running Locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API will be available at http://localhost:8000.

## Running with Docker

**Build and start the container:**

```bash
docker compose up --build
```

**Run in the background:**

```bash
docker compose up --build -d
```

**Stop the container:**

```bash
docker compose down
```

The API will be available at http://localhost:8000.

## Running Tests

Tests run locally against the app directly — no container required.

```bash
pip install -r requirements.txt
pytest tests/ -v
```

## API Endpoints

| Method | Path               | Description                                         |
| ------ | ------------------ | --------------------------------------------------- |
| `POST` | `/results`         | Upload a JUnit XML file and store the parsed result |
| `GET`  | `/results`         | Return all stored test suite results                |
| `GET`  | `/results/{index}` | Return a single result by its index                 |
