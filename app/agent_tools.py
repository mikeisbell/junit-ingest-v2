import logging

from sqlalchemy.orm import Session

from .db_models import TestCaseORM, TestSuiteResultORM
from .vector_store import search_failures

logger = logging.getLogger(__name__)

TOOL_DEFINITIONS = [
    {
        "name": "search_failures",
        "description": "Search for test failures semantically similar to a query string. Use this when the user asks about specific kinds of failures or error messages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "n_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_suite_by_id",
        "description": "Fetch a specific test suite result by its integer ID. Use this when the user references a specific suite ID or wants details about a particular test run.",
        "input_schema": {
            "type": "object",
            "properties": {
                "suite_id": {"type": "integer"},
            },
            "required": ["suite_id"],
        },
    },
    {
        "name": "get_recent_failures",
        "description": "Fetch the most recent failed test cases across all suites. Use this when the user asks about recent failures or wants to see what has been failing lately.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10, "maximum": 50},
            },
            "required": [],
        },
    },
    {
        "name": "get_failure_stats",
        "description": "Count how many times each test case has failed across all suites. Use this when the user asks about recurring failures, flaky tests, or which tests fail most often.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10, "maximum": 50},
            },
            "required": [],
        },
    },
]


def execute_search_failures(inputs: dict) -> dict:
    results = search_failures(query=inputs["query"], n_results=inputs.get("n_results", 5))
    if not results:
        return {"results": [], "message": "No similar failures found."}
    return {"results": results}


def execute_get_suite_by_id(inputs: dict, db: Session) -> dict:
    suite_id = inputs["suite_id"]
    row = db.query(TestSuiteResultORM).filter(TestSuiteResultORM.id == suite_id).first()
    if row is None:
        return {"error": f"Suite {suite_id} not found."}
    return {
        "id": row.id,
        "name": row.name,
        "total_tests": row.total_tests,
        "total_failures": row.total_failures,
        "total_errors": row.total_errors,
        "total_skipped": row.total_skipped,
        "elapsed_time": row.elapsed_time,
        "test_cases": [
            {
                "name": tc.name,
                "status": tc.status,
                "failure_message": tc.failure_message,
            }
            for tc in row.test_cases
        ],
    }


def execute_get_recent_failures(inputs: dict, db: Session) -> dict:
    limit = inputs.get("limit", 10)
    rows = (
        db.query(TestCaseORM)
        .filter(TestCaseORM.status.in_(["failed", "error"]))
        .order_by(TestCaseORM.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "failures": [
            {
                "test_case_id": row.id,
                "suite_id": row.suite_id,
                "name": row.name,
                "status": row.status,
                "failure_message": row.failure_message,
            }
            for row in rows
        ]
    }


def execute_get_failure_stats(inputs: dict, db: Session) -> dict:
    limit = inputs.get("limit", 10)
    rows = (
        db.query(TestCaseORM)
        .filter(TestCaseORM.status.in_(["failed", "error"]))
        .all()
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.name] = counts.get(row.name, 0) + 1
    sorted_stats = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return {
        "stats": [{"name": name, "failure_count": count} for name, count in sorted_stats]
    }


def execute_tool(tool_name: str, tool_inputs: dict, db: Session) -> dict:
    if tool_name == "search_failures":
        return execute_search_failures(tool_inputs)
    elif tool_name == "get_suite_by_id":
        return execute_get_suite_by_id(tool_inputs, db)
    elif tool_name == "get_recent_failures":
        return execute_get_recent_failures(tool_inputs, db)
    elif tool_name == "get_failure_stats":
        return execute_get_failure_stats(tool_inputs, db)
    else:
        return {"error": f"Unknown tool: {tool_name}"}
