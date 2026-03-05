from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .database import Base


class TestSuiteResultORM(Base):
    __tablename__ = "test_suite_results"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    total_tests = Column(Integer, nullable=False)
    total_failures = Column(Integer, nullable=False)
    total_errors = Column(Integer, nullable=False)
    total_skipped = Column(Integer, nullable=False)
    elapsed_time = Column(Float, nullable=False)

    test_cases = relationship(
        "TestCaseORM", back_populates="suite", cascade="all, delete-orphan"
    )


class TestCaseORM(Base):
    __tablename__ = "test_cases"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    failure_message = Column(String, nullable=True)
    suite_id = Column(Integer, ForeignKey("test_suite_results.id"), nullable=False)

    suite = relationship("TestSuiteResultORM", back_populates="test_cases")


class APIKeyORM(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_hash = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    is_active = Column(Boolean, nullable=False, default=True)
