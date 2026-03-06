import json
import logging
import os

import anthropic
from sqlalchemy.orm import Session

from .agent_tools import execute_get_failure_stats, execute_get_suite_by_id, execute_search_failures
from .logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a test failure analyst. You will be given data about a failing test suite "
    "and asked to produce a structured diagnostic report. You must respond with valid JSON only. "
    "No markdown, no preamble, no explanation outside the JSON structure."
)


def investigate_suite(suite_id: int, db: Session) -> dict:
    steps_executed: list[str] = []

    # ------------------------------------------------------------------
    # Step 1: Fetch suite details
    # ------------------------------------------------------------------
    suite_details = execute_get_suite_by_id(inputs={"suite_id": suite_id}, db=db)
    if "error" in suite_details:
        return {"error": f"Suite {suite_id} not found.", "suite_id": suite_id}
    logger.info(
        "investigation_step",
        extra={"suite_id": suite_id, "step": "fetch_suite", "status": "complete"},
    )
    steps_executed.append("fetch_suite")

    # ------------------------------------------------------------------
    # Step 2: Search for similar historical failures
    # ------------------------------------------------------------------
    failed_cases = [
        tc
        for tc in suite_details.get("test_cases", [])
        if tc["status"] in ("failed", "error") and tc.get("failure_message")
    ]

    seen_ids: set[int] = set()
    similar_results: list[dict] = []
    for tc in failed_cases:
        search_result = execute_search_failures(
            inputs={"query": tc["failure_message"], "n_results": 3}
        )
        for item in search_result.get("results", []):
            tc_id = item.get("test_case_id")
            if tc_id not in seen_ids:
                seen_ids.add(tc_id)
                similar_results.append(item)

    logger.info(
        "investigation_step",
        extra={
            "suite_id": suite_id,
            "step": "search_similar",
            "failure_count": len(failed_cases),
            "similar_count": len(similar_results),
        },
    )
    steps_executed.append("search_similar")

    # ------------------------------------------------------------------
    # Step 3: Get failure stats
    # ------------------------------------------------------------------
    stats_result = execute_get_failure_stats(inputs={"limit": 10}, db=db)
    logger.info(
        "investigation_step",
        extra={"suite_id": suite_id, "step": "get_stats"},
    )
    steps_executed.append("get_stats")

    # ------------------------------------------------------------------
    # Step 4: Generate structured report via Claude
    # ------------------------------------------------------------------
    user_message = f"""Here is the data for your analysis.

## Suite Details
{json.dumps(suite_details, indent=2)}

## Similar Historical Failures
{json.dumps(similar_results, indent=2)}

## Failure Stats (top recurring failures across all suites)
{json.dumps(stats_result.get("stats", []), indent=2)}

Please produce a JSON object with exactly these keys:
- "summary": a 2-3 sentence plain English summary of what failed and the likely impact
- "root_cause_hypotheses": a list of dicts, each with keys "hypothesis" (string) and "confidence" (one of "high", "medium", "low")
- "recurring_patterns": a list of dicts, each with keys "test_name" (string) and "failure_count" (int) for tests that appear in the stats with more than one failure
- "recommended_next_steps": a list of strings, each a concrete actionable recommendation

Respond with valid JSON only. No markdown, no preamble."""

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            raw_text = block.text
            break

    try:
        report = json.loads(raw_text)
    except (json.JSONDecodeError, ValueError) as exc:
        report = {
            "error": f"Failed to parse Claude response as JSON: {exc}",
            "raw_response": raw_text,
        }

    logger.info(
        "investigation_step",
        extra={"suite_id": suite_id, "step": "generate_report"},
    )
    steps_executed.append("generate_report")

    # ------------------------------------------------------------------
    # Step 5: Assemble and return the final report
    # ------------------------------------------------------------------
    return {
        "suite_id": suite_details["id"],
        "suite_name": suite_details["name"],
        "total_tests": suite_details["total_tests"],
        "total_failures": suite_details["total_failures"],
        "total_errors": suite_details["total_errors"],
        "similar_failures_found": len(similar_results),
        "report": report,
        "steps_executed": steps_executed,
    }
