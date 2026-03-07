import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)


@dataclass
class DevRevIssue:
    title: str
    body: str
    priority: str = "p2"


def create_issue(issue: DevRevIssue) -> dict:
    mock_mode = os.getenv("DEVREV_MOCK", "false").lower() == "true"

    if mock_mode:
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

    if status == 201:
        result = json.loads(body)
        work_item_id = result.get("work", {}).get("id", "unknown")
        logger.info(
            "devrev_issue_created",
            extra={"title": issue.title, "work_item_id": work_item_id},
        )
        return result
    else:
        logger.error(
            "devrev_issue_failed",
            extra={"status_code": status, "response_body": body},
        )
        raise RuntimeError(f"DevRev API returned status {status}: {body}")
