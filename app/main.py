import json
import logging
import os
from contextlib import asynccontextmanager

import redis
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import database, db_models
from .auth import generate_key, hash_key, require_admin_token, require_api_key
from .celery_app import celery_app
from .database import get_db
from .logging_config import configure_logging
from .middleware import TraceIDMiddleware
from .models import TestCase, TestSuiteResult
from .parser import JUnitParseError, parse_junit_xml
from .agent_tasks import run_agent_task
from .cache import get_cached, make_search_cache_key, set_cached
from .ci_webhook import process_ci_webhook
from .investigator_tasks import investigate_suite_task
from .rate_limiter import check_rate_limit
from .tasks import analyze_failures_task, embed_failures_task
from .vector_store import _get_client, search_failures
from .graph import get_gap_analysis, get_tests_for_modules, ingest_suite_to_graph

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

DEMO_SEED_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "demo", "data", "seed_data.json"
)

DEMO_FEATURE_MAP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "demo", "data", "feature_map.json"
)

configure_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.Base.metadata.create_all(bind=database.engine)
    from .graph import get_driver, init_graph, seed_graph
    driver = get_driver()
    if driver is not None:
        init_graph(driver)
        if os.path.exists(DEMO_SEED_PATH):
            with open(DEMO_SEED_PATH) as f:
                seed_data = json.load(f)
            seed_graph(driver, seed_data)
    app.state.neo4j_driver = driver
    if os.path.exists(DEMO_FEATURE_MAP_PATH):
        with open(DEMO_FEATURE_MAP_PATH) as f:
            app.state.feature_map = json.load(f)
    else:
        app.state.feature_map = {}
    yield
    if driver is not None:
        driver.close()


app = FastAPI(title="JUnit XML Ingestion Service", lifespan=lifespan)
app.add_middleware(TraceIDMiddleware)


def _orm_to_pydantic(row: db_models.TestSuiteResultORM) -> TestSuiteResult:
    return TestSuiteResult(
        name=row.name,
        total_tests=row.total_tests,
        total_failures=row.total_failures,
        total_errors=row.total_errors,
        total_skipped=row.total_skipped,
        elapsed_time=row.elapsed_time,
        test_cases=[
            TestCase(name=tc.name, status=tc.status, failure_message=tc.failure_message)
            for tc in row.test_cases
        ],
    )


@app.post("/results", response_model=TestSuiteResult)
async def ingest_results(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> TestSuiteResult:
    """Accept a JUnit XML file upload, parse it, and return structured results."""
    allowed, remaining = check_rate_limit(api_key.name)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum 30 requests per minute per API key.")
    content = await file.read()
    logger.info("ingest_started", extra={"upload_filename": file.filename, "content_length": len(content), "api_key_name": api_key.name})
    try:
        result = parse_junit_xml(content)
    except JUnitParseError as exc:
        logger.warning("ingest_parse_error", extra={"error": str(exc)})
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    db_result = db_models.TestSuiteResultORM(
        name=result.name,
        total_tests=result.total_tests,
        total_failures=result.total_failures,
        total_errors=result.total_errors,
        total_skipped=result.total_skipped,
        elapsed_time=result.elapsed_time,
        test_cases=[
            db_models.TestCaseORM(
                name=tc.name,
                status=tc.status,
                failure_message=tc.failure_message,
            )
            for tc in result.test_cases
        ],
    )
    db.add(db_result)
    db.commit()
    db.refresh(db_result)
    logger.info(
        "ingest_complete",
        extra={
            "suite_id": db_result.id,
            "total_tests": db_result.total_tests,
            "total_failures": db_result.total_failures,
        },
    )

    try:
        ingest_suite_to_graph(
            getattr(request.app.state, "neo4j_driver", None),
            result,
            request.app.state.feature_map,
        )
    except Exception as exc:
        logger.warning("neo4j_ingest_warning", extra={"error": str(exc)})

    failed_cases = [
        {
            "test_case_id": tc.id,
            "name": tc.name,
            "failure_message": tc.failure_message,
        }
        for tc in db_result.test_cases
        if tc.failure_message
    ]
    if failed_cases:
        embed_failures_task.delay(suite_id=db_result.id, test_cases=failed_cases)
        logger.info("embed_task_queued", extra={"suite_id": db_result.id})

    return JSONResponse(
        content=jsonable_encoder(_orm_to_pydantic(db_result)),
        headers={"X-RateLimit-Remaining": str(remaining)},
    )


@app.get("/results", response_model=list[TestSuiteResult])
async def get_results(
    db: Session = Depends(get_db),
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> list[TestSuiteResult]:
    """Return all previously ingested test suite results."""
    allowed, remaining = check_rate_limit(api_key.name)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum 30 requests per minute per API key.")
    rows = db.query(db_models.TestSuiteResultORM).all()
    return JSONResponse(
        content=jsonable_encoder([_orm_to_pydantic(row) for row in rows]),
        headers={"X-RateLimit-Remaining": str(remaining)},
    )


@app.get("/results/{result_id}", response_model=TestSuiteResult)
async def get_result(
    result_id: int,
    db: Session = Depends(get_db),
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> TestSuiteResult:
    """Return a single previously ingested test suite result by its database ID."""
    allowed, remaining = check_rate_limit(api_key.name)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum 30 requests per minute per API key.")
    row = (
        db.query(db_models.TestSuiteResultORM)
        .filter(db_models.TestSuiteResultORM.id == result_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"No result with id {result_id}")
    return JSONResponse(
        content=jsonable_encoder(_orm_to_pydantic(row)),
        headers={"X-RateLimit-Remaining": str(remaining)},
    )


@app.get("/search")
async def search_results(
    q: str = Query(default=""),
    n: int = Query(default=5, ge=1, le=20),
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> dict:
    """Search for similar failure messages using semantic similarity."""
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter q is required.")
    allowed, remaining = check_rate_limit(api_key.name)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum 30 requests per minute per API key.")
    key = make_search_cache_key(q, n)
    cached = get_cached(key)
    if cached:
        logger.info("cache_hit", extra={"endpoint": "search", "query": q})
        return JSONResponse(content=cached, headers={"X-RateLimit-Remaining": str(remaining)})
    logger.info("cache_miss", extra={"endpoint": "search"})
    logger.info("search_started", extra={"query": q, "api_key_name": api_key.name})
    results = search_failures(query=q, n_results=n)
    logger.info("search_complete", extra={"query": q, "result_count": len(results), "api_key_name": api_key.name})
    response_dict = {"query": q, "results": results}
    set_cached(key, response_dict)
    return JSONResponse(content=response_dict, headers={"X-RateLimit-Remaining": str(remaining)})


class AnalyzeRequest(BaseModel):
    query: str
    n: int = Field(default=5, ge=1, le=20)


class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1)


class ChurnRequest(BaseModel):
    """Request body for POST /graph/churn."""

    modules: list[str]


@app.post("/keys", status_code=201)
async def create_api_key(
    body: CreateKeyRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_token),
) -> dict:
    """Issue a new API key. Requires X-Admin-Token header."""
    allowed, remaining = check_rate_limit("admin")
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum 30 requests per minute per API key.")
    plaintext = generate_key()
    new_record = db_models.APIKeyORM(name=body.name, key_hash=hash_key(plaintext))
    db.add(new_record)
    db.commit()
    db.refresh(new_record)
    logger.info("api_key_created", extra={"api_key_name": body.name})
    # This is the only time the plaintext key is returned. It is not stored.
    return JSONResponse(
        content={
            "key": plaintext,
            "name": new_record.name,
            "created_at": new_record.created_at.isoformat(),
        },
        status_code=201,
        headers={"X-RateLimit-Remaining": str(remaining)},
    )


@app.post("/analyze", status_code=202)
async def analyze_results(
    body: AnalyzeRequest,
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> dict:
    """Dispatch an async analysis job and return the task ID."""
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    allowed, remaining = check_rate_limit(api_key.name)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum 30 requests per minute per API key.")
    task = analyze_failures_task.delay(query=body.query, n_results=body.n)
    logger.info("analyze_task_queued", extra={"query": body.query, "api_key_name": api_key.name})
    return JSONResponse(
        content={"task_id": task.id, "status": "pending"},
        status_code=202,
        headers={"X-RateLimit-Remaining": str(remaining)},
    )


@app.post("/agent", status_code=202)
async def agent_query(
    body: AnalyzeRequest,
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> dict:
    """Dispatch an async agent job and return the task ID."""
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    allowed, remaining = check_rate_limit(api_key.name)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum 30 requests per minute per API key.")
    task = run_agent_task.delay(query=body.query)
    logger.info("agent_task_queued", extra={"query": body.query})
    return JSONResponse(
        content={"task_id": task.id, "status": "pending"},
        status_code=202,
        headers={"X-RateLimit-Remaining": str(remaining)},
    )


@app.get("/agent/{task_id}")
async def get_agent_result(
    task_id: str,
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> dict:
    """Poll for the result of an async agent job."""
    allowed, remaining = check_rate_limit(api_key.name)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum 30 requests per minute per API key.")
    result = celery_app.AsyncResult(task_id)
    if result.state in ("PENDING", "STARTED"):
        return JSONResponse(content={"task_id": task_id, "status": "pending"}, headers={"X-RateLimit-Remaining": str(remaining)})
    if result.state == "SUCCESS":
        return JSONResponse(content={"task_id": task_id, "status": "complete", **result.result}, headers={"X-RateLimit-Remaining": str(remaining)})
    return JSONResponse(content={"task_id": task_id, "status": "failed", "error": str(result.result)}, headers={"X-RateLimit-Remaining": str(remaining)})


@app.post("/investigate/{suite_id}", status_code=202)
async def investigate_suite_endpoint(
    suite_id: int,
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> dict:
    """Dispatch an async investigation job for a suite and return the task ID."""
    allowed, remaining = check_rate_limit(api_key.name)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum 30 requests per minute per API key.")
    task = investigate_suite_task.delay(suite_id=suite_id)
    logger.info(
        "investigate_task_queued",
        extra={"suite_id": suite_id, "api_key_name": api_key.name},
    )
    return JSONResponse(
        content={"task_id": task.id, "status": "pending", "suite_id": suite_id},
        status_code=202,
        headers={"X-RateLimit-Remaining": str(remaining)},
    )


@app.get("/investigate/result/{task_id}")
async def get_investigate_result(
    task_id: str,
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> dict:
    """Poll for the result of an async investigation job."""
    allowed, remaining = check_rate_limit(api_key.name)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum 30 requests per minute per API key.")
    result = celery_app.AsyncResult(task_id)
    if result.state in ("PENDING", "STARTED"):
        return JSONResponse(content={"task_id": task_id, "status": "pending"}, headers={"X-RateLimit-Remaining": str(remaining)})
    if result.state == "SUCCESS":
        return JSONResponse(content={"task_id": task_id, "status": "complete", **result.result}, headers={"X-RateLimit-Remaining": str(remaining)})
    return JSONResponse(content={"task_id": task_id, "status": "failed", "error": str(result.result)}, headers={"X-RateLimit-Remaining": str(remaining)})


@app.get("/analyze/{task_id}")
async def get_analyze_result(
    task_id: str,
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> dict:
    """Poll for the result of an async analysis job."""
    allowed, remaining = check_rate_limit(api_key.name)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum 30 requests per minute per API key.")
    result = celery_app.AsyncResult(task_id)
    if result.state in ("PENDING", "STARTED"):
        return JSONResponse(content={"task_id": task_id, "status": "pending"}, headers={"X-RateLimit-Remaining": str(remaining)})
    if result.state == "SUCCESS":
        return JSONResponse(content={"task_id": task_id, "status": "complete", **result.result}, headers={"X-RateLimit-Remaining": str(remaining)})
    return JSONResponse(content={"task_id": task_id, "status": "failed", "error": str(result.result)}, headers={"X-RateLimit-Remaining": str(remaining)})


@app.get("/health")
async def health_check(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    """Check the status of all dependencies and return their health."""
    deps: dict = {}

    # Postgres check
    try:
        db.execute(text("SELECT 1"))
        deps["postgres"] = {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        deps["postgres"] = {"status": "error", "detail": str(exc)}

    # ChromaDB check
    try:
        _get_client().heartbeat()
        deps["chromadb"] = {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        deps["chromadb"] = {"status": "error", "detail": str(exc)}

    # Redis check
    try:
        redis.from_url(REDIS_URL).ping()
        deps["redis"] = {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        deps["redis"] = {"status": "error", "detail": str(exc)}

    # Neo4j check
    try:
        neo4j_driver = getattr(request.app.state, "neo4j_driver", None)
        if neo4j_driver is None:
            raise RuntimeError("driver not initialized")
        with neo4j_driver.session() as session:
            session.run("RETURN 1")
        deps["neo4j"] = {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        deps["neo4j"] = {"status": "error", "detail": str(exc)}

    all_ok = all(v["status"] == "ok" for v in deps.values())
    status_code = 200 if all_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if all_ok else "degraded",
            "dependencies": deps,
        },
    )


# This endpoint is intentionally unauthenticated for CI pipeline use.
@app.post("/webhook/ci")
async def ci_webhook(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    """Accept a JUnit XML file from a CI pipeline and conditionally create a DevRev issue."""
    content = await file.read()
    try:
        suite = parse_junit_xml(content)
    except JUnitParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    failure_rate = round(suite.total_failures / suite.total_tests, 4) if suite.total_tests > 0 else 0.0

    devrev_result = None
    issue_created = False
    try:
        devrev_result = process_ci_webhook(
            suite, db, driver=getattr(request.app.state, "neo4j_driver", None)
        )
        if devrev_result is not None:
            issue_created = True
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return JSONResponse(
        content={
            "suite": suite.name,
            "tests": suite.total_tests,
            "failures": suite.total_failures,
            "failure_rate": failure_rate,
            "issue_created": issue_created,
            "devrev_result": devrev_result,
        }
    )


@app.post("/graph/churn")
async def graph_churn(
    request: Request,
    body: ChurnRequest,
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> dict:
    """Return prioritized test cases for the given list of changed code modules.

    Traverses the knowledge graph from CodeModule -> Feature -> TestCase.
    Returns 503 if Neo4j is unavailable.
    """
    driver = getattr(request.app.state, "neo4j_driver", None)
    if driver is None:
        raise HTTPException(status_code=503, detail="graph unavailable")
    tests = get_tests_for_modules(driver, body.modules)
    return {
        "changed_modules": body.modules,
        "recommended_tests": tests,
        "total_recommended": len(tests),
    }


@app.get("/graph/gaps/{bug_id}")
async def graph_gaps(
    bug_id: str,
    request: Request,
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> dict:
    """Return feature coverage analysis for the given bug ID.

    Traverses the knowledge graph from Bug -> Feature <- TestCase.
    Returns 404 if the bug is not found, 503 if Neo4j is unavailable.
    """
    driver = getattr(request.app.state, "neo4j_driver", None)
    if driver is None:
        raise HTTPException(status_code=503, detail="graph unavailable")
    result = get_gap_analysis(driver, bug_id)
    if result.get("error") == "bug not found":
        raise HTTPException(status_code=404, detail="bug not found")
    if result.get("error") == "graph unavailable":
        raise HTTPException(status_code=503, detail="graph unavailable")
    return result
