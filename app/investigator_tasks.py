import logging

from .celery_app import celery_app
from .database import SessionLocal
from .investigator import investigate_suite
from .logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=10)
def investigate_suite_task(self, suite_id: int) -> dict:
    db = SessionLocal()
    try:
        result = investigate_suite(suite_id=suite_id, db=db)
        logger.info(
            "investigate_task_complete",
            extra={
                "suite_id": suite_id,
                "steps_executed": result.get("steps_executed", []),
            },
        )
        return result
    except Exception as exc:
        logger.error(
            "investigate_task_failed",
            extra={"suite_id": suite_id, "error": str(exc)},
        )
        raise self.retry(exc=exc)
    finally:
        db.close()
