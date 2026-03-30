"""Database connection for the bug tracker.

Uses a separate Postgres database from the pipeline app to simulate
the boundary between the pipeline and an external bug tracking system.
In production this module would be replaced by calls to a real bug
tracker API such as DevRev, Jira, or Linear.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BUG_TRACKER_DATABASE_URL = os.getenv(
    "BUG_TRACKER_DATABASE_URL",
    "postgresql://postgres:postgres@postgres:5432/bug_tracker",
)

engine = create_engine(BUG_TRACKER_DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Create all bug tracker tables if they do not exist."""
    from .models import BugORM  # noqa: F401
    Base.metadata.create_all(bind=engine)
