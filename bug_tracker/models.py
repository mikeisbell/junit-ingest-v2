"""ORM model for the bug tracker database.

In production this schema would live in the external bug tracker system.
The JSON columns for failure_signatures, linked_builds, and linked_test_names
represent relationships that in a production system would be normalized
junction tables or external API references.
"""
from sqlalchemy import Boolean, Column, JSON, String

from .database import Base


class BugORM(Base):
    __tablename__ = "bugs"

    id = Column(String, primary_key=True)        # e.g. "BUG-001"
    title = Column(String, nullable=False)
    status = Column(String, nullable=False, default="open")
    severity = Column(String, nullable=False, default="medium")
    feature = Column(String, nullable=True)
    escaped = Column(Boolean, nullable=False, default=False)
    failure_signatures = Column(JSON, nullable=False, default=list)
    linked_builds = Column(JSON, nullable=False, default=list)
    linked_test_names = Column(JSON, nullable=False, default=list)
