"""
This module processes CI pipeline webhook events.

It ingests JUnit XML results, runs AI-powered failure analysis via investigate_suite(),
and creates a DevRev issue when the failure rate exceeds a configurable threshold.

The failure-rate threshold is controlled by the CI_FAILURE_THRESHOLD environment
variable (default 0.2, i.e. 20% of tests failing).
"""
import logging
import os

from sqlalchemy.orm import Session

from . import db_models
from .integrations.devrev import DevRevIssue, create_issue
from .investigator import investigate_suite
from .logging_config import configure_logging
from .models import TestSuiteResult

configure_logging()

logger = logging.getLogger(__name__)


def process_ci_webhook(suite: TestSuiteResult, db: Session, driver=None) -> dict | None:
    """Evaluate a parsed test suite and create a DevRev issue if warranted.

    The failure rate (failures / total_tests) is computed and compared against
    CI_FAILURE_THRESHOLD. If the rate is zero or below the threshold, no action
    is taken. Otherwise the suite is persisted to Postgres, investigate_suite()
    is called synchronously to produce an AI-generated diagnostic report, and
    the report is formatted into a Markdown body before being submitted to DevRev
    via create_issue().

    Args:
        suite:  The fully-parsed TestSuiteResult from the incoming CI webhook payload.
        db:     SQLAlchemy session used to persist the suite and passed through to
                investigate_suite() for historical database lookups.
        driver: Optional Neo4j driver forwarded to investigate_suite() for the
                graph_context step. If None, graph context is skipped.

    Returns:
        The DevRev API response dict if an issue was created, or None if the failure
        rate was zero or below the configured threshold.
    """
    threshold = float(os.getenv("CI_FAILURE_THRESHOLD", "0.2"))

    # Use failures / tests rather than (failures + errors) / tests. Errors
    # represent infrastructure or setup problems (e.g. missing fixtures) rather
    # than assertion failures. Separating them lets the threshold reflect genuine
    # test-logic failures without infrastructure noise skewing the rate.
    failure_rate = suite.total_failures / suite.total_tests if suite.total_tests > 0 else 0.0

    if failure_rate == 0 or suite.total_failures == 0:
        return None

    if failure_rate < threshold:
        logger.info(
            "ci_threshold_not_met",
            extra={
                "suite_name": suite.name,
                "failure_rate": failure_rate,
                "threshold": threshold,
            },
        )
        return None

    try:
        # The suite must be persisted before investigate_suite() is called.
        # investigate_suite() retrieves the suite and its test cases from Postgres
        # by ID (via execute_get_suite_by_id). Without a committed row in the DB
        # those queries would return nothing and the report would be empty.
        db_suite = db_models.TestSuiteResultORM(
            name=suite.name,
            total_tests=suite.total_tests,
            total_failures=suite.total_failures,
            total_errors=suite.total_errors,
            total_skipped=suite.total_skipped,
            elapsed_time=suite.elapsed_time,
            test_cases=[
                db_models.TestCaseORM(
                    name=tc.name,
                    status=tc.status,
                    failure_message=tc.failure_message,
                )
                for tc in suite.test_cases
            ],
        )
        db.add(db_suite)
        db.commit()
        db.refresh(db_suite)

        # investigate_suite is called synchronously here—not via a Celery task—
        # because the webhook handler must assemble the DevRev issue body from the
        # analysis result before returning. The analysis latency is bounded by the
        # Claude API call (~2–5 s), which is acceptable for a webhook context.
        report_outer = investigate_suite(db_suite.id, db, driver=driver)
        inner_report = report_outer.get("report", report_outer)

        summary = inner_report.get("summary", "")
        hypotheses = inner_report.get("root_cause_hypotheses", [])
        next_steps = inner_report.get("recommended_next_steps", [])

        # Assign p1 at a 50% or higher failure rate. At that point more than half
        # of the suite is broken, indicating a systemic regression that warrants
        # immediate attention rather than a routine p2 follow-up.
        priority = "p1" if failure_rate >= 0.5 else "p2"
        title = f"CI Failure: {suite.name} ({suite.total_failures}/{suite.total_tests} tests failed)"

        body_lines = [
            f"## Summary\n{summary}",
            "\n## Root Cause Hypotheses",
        ]
        for h in hypotheses:
            body_lines.append(
                f"- {h.get('hypothesis', '')} (confidence: {h.get('confidence', '')})"
            )
        body_lines.append("\n## Recommended Next Steps")
        for step in next_steps:
            body_lines.append(f"- {step}")
        body_lines.append("\nGenerated by junit-ingest-v2 AI investigator")

        body = "\n".join(body_lines)
        issue = DevRevIssue(title=title, body=body, priority=priority)
        result = create_issue(issue)
    except Exception as exc:
        logger.error("ci_webhook_error", extra={"error": str(exc)})
        raise

    mock_mode = os.getenv("DEVREV_MOCK", "false").lower() == "true"
    logger.info(
        "ci_devrev_issue_dispatched",
        extra={
            "suite_name": suite.name,
            "failure_rate": failure_rate,
            "mock": mock_mode,
        },
    )
    return result
