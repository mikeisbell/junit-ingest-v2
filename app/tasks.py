import logging

from .celery_app import celery_app
from .logging_config import configure_logging
from .rag import analyze_failures
from .vector_store import embed_failures, search_failures

configure_logging()

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=5)
def embed_failures_task(self, suite_id: int, test_cases: list) -> dict:
    try:
        embed_failures(suite_id=suite_id, test_cases=test_cases)
        logger.info("embed_task_complete", extra={"suite_id": suite_id})
        return {"suite_id": suite_id, "status": "complete"}
    except Exception as exc:
        logger.error("embed_task_failed", extra={"suite_id": suite_id, "error": str(exc)})
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def analyze_failures_task(self, query: str, n_results: int) -> dict:
    try:
        results = search_failures(query=query, n_results=n_results)
        analysis = analyze_failures(query=query, failures=results)
        logger.info("analyze_task_complete", extra={"query": query, "failures_used": len(results)})
        return {"query": query, "failures_used": len(results), "analysis": analysis}
    except Exception as exc:
        logger.error("analyze_task_failed", extra={"query": query, "error": str(exc)})
        raise self.retry(exc=exc)
