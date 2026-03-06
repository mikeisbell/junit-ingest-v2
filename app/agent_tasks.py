import logging

from .agent import run_agent
from .celery_app import celery_app
from .database import SessionLocal
from .logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=10)
def run_agent_task(self, query: str) -> dict:
    db = SessionLocal()
    try:
        result = run_agent(query=query, db=db)
        logger.info(
            "agent_task_complete",
            extra={
                "query": query,
                "tools_called": result["tools_called"],
                "iterations": result["iterations"],
            },
        )
        return result
    except Exception as exc:
        logger.error("agent_task_failed", extra={"query": query, "error": str(exc)})
        raise self.retry(exc=exc)
    finally:
        db.close()
