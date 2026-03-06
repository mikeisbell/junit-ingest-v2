import os

from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "junit_ingest",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.tasks", "app.agent_tasks"]
)

celery_app.conf.update(
    result_expires=86400,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
)
