"""
This module implements the agentic investigation pattern (Layer 8, fixed workflow).

Unlike the autonomous tool-use agent in agent.py, the investigator uses a deterministic
workflow: each data-gathering step is executed in a fixed order by Python code, and
Claude is invoked exactly once at the end to synthesize those results into a structured
report.

This pattern trades autonomy for predictability and cost control. The steps never
change based on intermediate inputs, so token usage is bounded and the execution path
is easy to trace in logs. Use this approach when the set of required data is known in
advance and consistency across runs matters more than flexibility.
"""
import json
import logging
import os

import anthropic
from sqlalchemy.orm import Session

from .agent_tools import execute_get_failure_stats, execute_get_suite_by_id, execute_search_failures
from .logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)

# The system prompt constrains Claude to return JSON only. Without this constraint
# Claude often wraps its response in markdown fences or adds explanatory prose,
# which would cause json.loads() to fail. Explicit reinforcement in both the
# system prompt and the user message minimises parse-failure retries.
SYSTEM_PROMPT = (
    "You are a test failure analyst. You will be given data about a failing test suite "
    "and asked to produce a structured diagnostic report. You must respond with valid JSON only. "
    "No markdown, no preamble, no explanation outside the JSON structure."
)


def investigate_suite(suite_id: int, db: Session, driver=None) -> dict:
    """Run a fixed five-step investigation pipeline for a persisted test suite.

    Steps:
        1. fetch_suite    – Retrieve full suite details (test cases, failure messages)
                            from Postgres via execute_get_suite_by_id.
        2. search_similar – For each failed test case, query the vector store for
                            historically similar failures to surface recurrence patterns.
        3. graph_context  – If a Neo4j driver is provided, traverse the knowledge graph
                            to find which features the failing tests cover and which
                            known bugs affect those features. Skipped if driver is None.
        4. get_stats      – Pull aggregate failure statistics for the top recurring
                            failures across all suites stored in the database.
        5. generate_report – Pass all collected data to Claude in a single prompt and
                             request a structured JSON diagnostic report.

    Args:
        suite_id: Primary key of the persisted TestSuiteResultORM row to investigate.
        db:       SQLAlchemy session for Postgres queries.
        driver:   Optional Neo4j driver for the graph_context step. If None, the
                  graph_context step is skipped and graph_context is set to {}.

    Returns:
        A dict containing suite metadata, the investigation report, and the list of
        steps executed. On JSON-parse failure the report key contains an error message
        and the raw Claude response for manual review.
    """
    steps_executed: list[str] = []

    # The workflow is intentionally fixed: Python drives every data-gathering step.
    # Letting Claude choose which tools to call (as in agent.py) would make token
    # usage and execution paths non-deterministic, complicating cost forecasting
    # and log-based debugging for a recurring, well-understood analysis task.

    # ------------------------------------------------------------------
    # Step 1: Fetch suite details
    # ------------------------------------------------------------------
    # Establishes the ground-truth record: which tests ran, which failed,
    # and what failure messages were emitted.
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
    # Vector-similarity search surfaces recurring patterns across past suite runs.
    # These matches give Claude historical context to distinguish a new regression
    # from a pre-existing flaky test.
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
    # Step 3: Graph context — relational coverage from the knowledge graph
    # ------------------------------------------------------------------
    # The graph traversal complements vector-similarity results by adding
    # relational context: which known bugs affect the features covered by each
    # failing test. Claude can use this to prioritise hypotheses tied to
    # already-escaped defects rather than pure statistical patterns.
    graph_context: dict = {}
    if driver is not None:
        with driver.session() as session:
            for tc in failed_cases:
                feature_result = session.run(
                    "MATCH (t:TestCase {name: $name})-[:COVERS]->(f:Feature) RETURN f.name AS feature",
                    name=tc["name"],
                )
                for freq in feature_result:
                    feature_name = freq["feature"]
                    if feature_name not in graph_context:
                        graph_context[feature_name] = {"bugs": []}
                    bug_result = session.run(
                        "MATCH (b:Bug)-[:AFFECTS]->(f:Feature {name: $feature}) "
                        "RETURN b.id AS id, b.title AS title, b.severity AS severity",
                        feature=feature_name,
                    )
                    for brec in bug_result:
                        graph_context[feature_name]["bugs"].append({
                            "id": brec["id"],
                            "title": brec["title"],
                            "severity": brec["severity"],
                        })
        logger.info(
            "investigation_step",
            extra={"suite_id": suite_id, "step": "graph_context", "feature_count": len(graph_context)},
        )
        steps_executed.append("graph_context")

    # ------------------------------------------------------------------
    # Step 4: Get failure stats
    # ------------------------------------------------------------------
    # Aggregate counts show which test names fail most frequently across all suites,
    # helping Claude weight its hypotheses toward systemic issues rather than
    # one-off failures.
    stats_result = execute_get_failure_stats(inputs={"limit": 10}, db=db)
    logger.info(
        "investigation_step",
        extra={"suite_id": suite_id, "step": "get_stats"},
    )
    steps_executed.append("get_stats")

    # ------------------------------------------------------------------
    # Step 5: Generate structured report via Claude
    # ------------------------------------------------------------------
    # Claude is called exactly once, after all data has been gathered. This keeps
    # token usage predictable and avoids the compounding cost of invoking the model
    # at each step. All gathered data is composed into a single prompt so Claude
    # has the full picture before producing the report.
    user_message = f"""Here is the data for your analysis.

## Suite Details
{json.dumps(suite_details, indent=2)}

## Similar Historical Failures
{json.dumps(similar_results, indent=2)}

## Graph Context
{json.dumps(graph_context, indent=2)}

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

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    estimated_cost = round((input_tokens / 1_000_000) * 3.00 + (output_tokens / 1_000_000) * 15.00, 6)
    logger.info(
        "claude_api_call",
        extra={
            "model": "claude-sonnet-4-6",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": estimated_cost,
            "caller": "investigate_suite",
        },
    )

    # Fallback: if Claude returns malformed JSON (e.g. a model update changes its
    # output format), capture the raw text rather than propagating an exception.
    # Callers can inspect report["raw_response"] to diagnose the issue without
    # losing the rest of the investigation result.
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
