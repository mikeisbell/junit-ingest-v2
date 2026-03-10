"""DevRev integration for junit-ingest-v2.

One of potentially many integrations in app/integrations/. To integrate with
a different issue tracker, add a new module alongside this one following the
same DevRevIssue dataclass and create_issue() pattern.

It supports two modes of operation:
- Mock mode (DEVREV_MOCK=true): logs the issue payload for development/demo purposes
  without making any real API calls.
- Live mode (DEVREV_MOCK=false or unset): submits the issue to the DevRev /works.create
  endpoint using a personal access token.

The operating mode is controlled by the DEVREV_MOCK environment variable.
"""
import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from ..logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)


@dataclass
class DevRevIssue:
    """Represents a DevRev work item (issue) to be created via the API.

    Attributes:
        title:    Short summary of the issue, used as the DevRev work item title.
        body:     Markdown-formatted detail body rendered inside the DevRev issue.
        priority: DevRev priority string (e.g. 'p1', 'p2'). Defaults to 'p2'.
    """

    title: str
    body: str
    priority: str = "p2"


def create_issue(issue: DevRevIssue) -> dict:
    mock_mode = os.getenv("DEVREV_MOCK", "false").lower() == "true"

    if mock_mode:
        # Mock mode emits a structured log entry rather than calling the API.
        # This lets development and demo environments exercise the full
        # ci_webhook pipeline—including issue creation—without requiring real
        # DevRev credentials or producing noise in the production issue tracker.
        logger.info(
            "devrev_mock_issue_created",
            extra={
                "title": issue.title,
                "body": issue.body,
                "priority": issue.priority,
                "mock": True,
            },
        )
        return {"mock": True, "title": issue.title, "status": "logged"}

    # Live mode
    pat = os.getenv("DEVREV_PAT", "")
    part_id = os.getenv("DEVREV_PART_ID", "")
    owner_id = os.getenv("DEVREV_OWNER_ID", "")

    # Validate credentials before constructing the request. Failing fast here
    # surfaces misconfiguration immediately rather than sending an unauthenticated
    # request and having to decode a cryptic 401 response from the API.
    if not pat or not part_id or not owner_id:
        raise RuntimeError(
            "DEVREV_PAT, DEVREV_PART_ID, and DEVREV_OWNER_ID must all be set in live mode"
        )

    payload = {
        "type": "issue",
        "title": issue.title,
        "body": issue.body,
        "applies_to_part": part_id,
        "owned_by": [owner_id],
        "priority": issue.priority,
    }
    data = json.dumps(payload).encode("utf-8")
    # urllib.request is part of the standard library; it requires no additional
    # dependencies. Adding requests or httpx for a single endpoint would
    # introduce transitive dependency risk without meaningful benefit.
    req = urllib.request.Request(
        "https://api.devrev.ai/works.create",
        data=data,
        headers={
            "Authorization": f"Bearer {pat}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        response = urllib.request.urlopen(req)
        status = response.status
        body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DevRev API request failed: {exc}") from exc

    # DevRev returns 201 Created on success—not 200 OK. Checking for exactly 201
    # avoids silently accepting unexpected 2xx codes that may indicate partial or
    # non-canonical processing.
    if status == 201:
        result = json.loads(body)
        work_item_id = result.get("work", {}).get("id", "unknown")
        # Log the issue title and the returned work_item_id together so operators
        # can correlate this log line with the DevRev issue in the UI without
        # having to replay the request.
        logger.info(
            "devrev_issue_created",
            extra={"title": issue.title, "work_item_id": work_item_id},
        )
        return result
    else:
        # Include status_code and the raw response_body so on-call engineers
        # can diagnose API errors from the log alone without reproducing the call.
        logger.error(
            "devrev_issue_failed",
            extra={"status_code": status, "response_body": body},
        )
        raise RuntimeError(f"DevRev API returned status {status}: {body}")
