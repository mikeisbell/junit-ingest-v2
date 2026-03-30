"""Mock bug tracker for junit-ingest-v2.

Stores bugs in memory backed by demo/data/bugs.json. Loaded from
demo/data/seed_data.json on first use if bugs.json does not exist.
Requires no external API calls or credentials.
"""
import json
import logging
import os

from .logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)

_BUGS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "demo", "data", "bugs.json"
)
_SEED_FILE = os.path.join(
    os.path.dirname(__file__), "..", "demo", "data", "seed_data.json"
)

_bug_store: dict[str, dict] = {}


def _save() -> None:
    """Persist the current bug store to demo/data/bugs.json."""
    with open(_BUGS_FILE, "w", encoding="utf-8") as fh:
        json.dump(_bug_store, fh, indent=2)


def _next_id() -> str:
    """Return the next BUG-NNN id based on the highest existing numeric id."""
    max_num = 0
    for bug_id in _bug_store:
        if bug_id.startswith("BUG-") and bug_id[4:].isdigit():
            max_num = max(max_num, int(bug_id[4:]))
    return f"BUG-{max_num + 1:03d}"


def _seed_from_file() -> None:
    """Populate _bug_store from demo/data/seed_data.json. Leaves store empty
    and logs a warning if the seed file is missing."""
    global _bug_store

    if not os.path.exists(_SEED_FILE):
        logger.warning("bug_seed_file_missing", extra={"path": _SEED_FILE})
        return

    with open(_SEED_FILE, encoding="utf-8") as fh:
        seed = json.load(fh)

    # Build a map from bug_id -> first feature from bug_feature_edges
    feature_by_bug: dict[str, str] = {}
    for edge in seed.get("bug_feature_edges", []):
        bug_id = edge["bug_id"]
        if bug_id not in feature_by_bug:
            feature_by_bug[bug_id] = edge["feature"]

    for bug in seed.get("bugs", []):
        bug_id = bug["id"]
        escaped = bug.get("escaped", False)
        _bug_store[bug_id] = {
            "id": bug_id,
            "title": bug["title"],
            "status": "open" if escaped else "resolved",
            "severity": bug["severity"],
            "feature": feature_by_bug.get(bug_id),
            "failure_signatures": [],
            "linked_builds": [],
            "linked_test_names": [],
            "escaped": escaped,
        }

    logger.info("bug_store_loaded", extra={"bug_count": len(_bug_store), "source": "seed_data.json"})


def load_bugs() -> None:
    """Load bug store from demo/data/bugs.json if it exists,
    otherwise seed from demo/data/seed_data.json bugs array.
    Called once on module import via module-level code."""
    global _bug_store
    _bug_store = {}

    if os.path.exists(_BUGS_FILE):
        with open(_BUGS_FILE, encoding="utf-8") as fh:
            _bug_store = json.load(fh)
        logger.info("bug_store_loaded", extra={"bug_count": len(_bug_store), "source": "bugs.json"})
        return

    _seed_from_file()


def get_all_bugs() -> list[dict]:
    """Return a copy of all bugs as a list."""
    return [dict(bug) for bug in _bug_store.values()]


def get_bug(bug_id: str) -> dict | None:
    """Return a single bug dict by ID, or None if not found."""
    bug = _bug_store.get(bug_id)
    return dict(bug) if bug is not None else None


def find_bug_by_signature(failure_message: str) -> dict | None:
    """Search all bugs for one whose failure_signatures list contains
    a substring that appears in failure_message (case-insensitive).
    Return the first match or None."""
    lower_msg = failure_message.lower()
    for bug in _bug_store.values():
        for sig in bug.get("failure_signatures", []):
            if sig.lower() in lower_msg:
                return dict(bug)
    return None


def create_bug(
    title: str,
    severity: str,
    feature: str | None,
    failure_signature: str,
    build: str,
    test_name: str,
) -> dict:
    """Create a new bug, add it to the store, persist to disk, and return it.

    Auto-assigns the next BUG-NNN id, sets status to 'open', escaped to False.
    """
    bug_id = _next_id()
    bug: dict = {
        "id": bug_id,
        "title": title,
        "status": "open",
        "severity": severity,
        "feature": feature,
        "failure_signatures": [failure_signature],
        "linked_builds": [build],
        "linked_test_names": [test_name],
        "escaped": False,
    }
    _bug_store[bug_id] = bug
    _save()
    logger.info("bug_created", extra={"bug_id": bug_id, "title": title, "feature": feature})
    return dict(bug)


def link_failure_to_bug(
    bug_id: str,
    build: str,
    test_name: str,
) -> dict | None:
    """Add build and test_name to an existing bug if not already present.

    Persist to disk. Return the updated bug or None if bug_id not found.
    """
    bug = _bug_store.get(bug_id)
    if bug is None:
        return None
    if build not in bug["linked_builds"]:
        bug["linked_builds"].append(build)
    if test_name not in bug["linked_test_names"]:
        bug["linked_test_names"].append(test_name)
    _save()
    logger.info("bug_linked", extra={"bug_id": bug_id, "build": build, "test_name": test_name})
    return dict(bug)


def set_bug_status(bug_id: str, status: str) -> dict | None:
    """Set bug status to 'open', 'resolved', or 'verified'.

    Persist to disk. Return the updated bug or None if not found.
    """
    bug = _bug_store.get(bug_id)
    if bug is None:
        return None
    bug["status"] = status
    _save()
    logger.info("bug_status_updated", extra={"bug_id": bug_id, "status": status})
    return dict(bug)


def get_bugs_for_feature(feature: str) -> list[dict]:
    """Return all bugs whose feature field matches the given feature name."""
    return [dict(bug) for bug in _bug_store.values() if bug.get("feature") == feature]


def reset_store() -> None:
    """Clear the in-memory store and reload from seed_data.json.
    Used by tests to get a clean state. Always re-seeds from seed_data.json,
    ignoring any persisted bugs.json."""
    global _bug_store
    _bug_store = {}
    _seed_from_file()
    _save()


# Load on import
load_bugs()
