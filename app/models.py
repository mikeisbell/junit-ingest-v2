from enum import Enum
from typing import Optional

from pydantic import BaseModel


class TestStatus(str, Enum):
    passed = "passed"
    failed = "failed"
    skipped = "skipped"
    error = "error"


class TestCase(BaseModel):
    name: str
    status: TestStatus
    failure_message: Optional[str] = None


class TestSuiteResult(BaseModel):
    name: str
    total_tests: int
    total_failures: int
    total_errors: int
    total_skipped: int
    elapsed_time: float
    test_cases: list[TestCase]
