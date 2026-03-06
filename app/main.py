import logging
import os
from contextlib import asynccontextmanager

import redis
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
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
from .tasks import analyze_failures_task, embed_failures_task
from .vector_store import _get_client, search_failures

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

configure_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.Base.metadata.create_all(bind=database.engine)
    yield


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
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> TestSuiteResult:
    """Accept a JUnit XML file upload, parse it, and return structured results."""
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

    return _orm_to_pydantic(db_result)


@app.get("/results", response_model=list[TestSuiteResult])
async def get_results(
    db: Session = Depends(get_db),
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> list[TestSuiteResult]:
    """Return all previously ingested test suite results."""
    rows = db.query(db_models.TestSuiteResultORM).all()
    return [_orm_to_pydantic(row) for row in rows]


@app.get("/results/{result_id}", response_model=TestSuiteResult)
async def get_result(
    result_id: int,
    db: Session = Depends(get_db),
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> TestSuiteResult:
    """Return a single previously ingested test suite result by its database ID."""
    row = (
        db.query(db_models.TestSuiteResultORM)
        .filter(db_models.TestSuiteResultORM.id == result_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"No result with id {result_id}")
    return _orm_to_pydantic(row)


@app.get("/search")
async def search_results(
    q: str = Query(default=""),
    n: int = Query(default=5, ge=1, le=20),
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> dict:
    """Search for similar failure messages using semantic similarity."""
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter q is required.")
    logger.info("search_started", extra={"query": q, "api_key_name": api_key.name})
    results = search_failures(query=q, n_results=n)
    logger.info("search_complete", extra={"query": q, "result_count": len(results), "api_key_name": api_key.name})
    return {"query": q, "results": results}


class AnalyzeRequest(BaseModel):
    query: str
    n: int = Field(default=5, ge=1, le=20)


class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1)


@app.post("/keys", status_code=201)
async def create_api_key(
    body: CreateKeyRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_token),
) -> dict:
    """Issue a new API key. Requires X-Admin-Token header."""
    plaintext = generate_key()
    new_record = db_models.APIKeyORM(name=body.name, key_hash=hash_key(plaintext))
    db.add(new_record)
    db.commit()
    db.refresh(new_record)
    logger.info("api_key_created", extra={"api_key_name": body.name})
    # This is the only time the plaintext key is returned. It is not stored.
    return {
        "key": plaintext,
        "name": new_record.name,
        "created_at": new_record.created_at.isoformat(),
    }


@app.post("/analyze", status_code=202)
async def analyze_results(
    body: AnalyzeRequest,
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> dict:
    """Dispatch an async analysis job and return the task ID."""
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="query is required")

    task = analyze_failures_task.delay(query=body.query, n_results=body.n)
    logger.info("analyze_task_queued", extra={"query": body.query, "api_key_name": api_key.name})
    return {
        "task_id": task.id,
        "status": "pending",
    }


@app.post("/agent", status_code=202)
async def agent_query(
    body: AnalyzeRequest,
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> dict:
    """Dispatch an async agent job and return the task ID."""
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="query is required")

    task = run_agent_task.delay(query=body.query)
    logger.info("agent_task_queued", extra={"query": body.query})
    return {
        "task_id": task.id,
        "status": "pending",
    }


@app.get("/agent/{task_id}")
async def get_agent_result(
    task_id: str,
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> dict:
    """Poll for the result of an async agent job."""
    result = celery_app.AsyncResult(task_id)
    if result.state in ("PENDING", "STARTED"):
        return {"task_id": task_id, "status": "pending"}
    if result.state == "SUCCESS":
        return {"task_id": task_id, "status": "complete", **result.result}
    return {"task_id": task_id, "status": "failed", "error": str(result.result)}


@app.get("/analyze/{task_id}")
async def get_analyze_result(
    task_id: str,
    api_key: db_models.APIKeyORM = Depends(require_api_key),
) -> dict:
    """Poll for the result of an async analysis job."""
    result = celery_app.AsyncResult(task_id)
    if result.state in ("PENDING", "STARTED"):
        return {"task_id": task_id, "status": "pending"}
    if result.state == "SUCCESS":
        return {"task_id": task_id, "status": "complete", **result.result}
    return {"task_id": task_id, "status": "failed", "error": str(result.result)}


@app.get("/health")
async def health_check(db: Session = Depends(get_db)) -> JSONResponse:
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

    all_ok = all(v["status"] == "ok" for v in deps.values())
    status_code = 200 if all_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if all_ok else "degraded",
            "dependencies": deps,
        },
    )
