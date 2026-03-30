"""Bug tracker CRUD operations backed by Postgres.

Each public function manages its own database session. No module-level
in-memory state. All reads and writes go directly to Postgres.
"""
import json
import logging
from pathlib import Path

from .database import SessionLocal, init_db
from .models import BugORM

logger = logging.getLogger(__name__)


def _bug_to_dict(bug: BugORM) -> dict:
    return {
        "id": bug.id,
        "title": bug.title,
        "status": bug.status,
        "severity": bug.severity,
        "feature": bug.feature,
        "escaped": bug.escaped,
        "failure_signatures": bug.failure_signatures or [],
        "linked_builds": bug.linked_builds or [],
        "linked_test_names": bug.linked_test_names or [],
    }


def _next_id(session) -> str:
    existing = [row.id for row in session.query(BugORM.id).all()]
    nums = []
    for bid in existing:
        try:
            nums.append(int(bid.split("-")[1]))
        except (IndexError, ValueError):
            pass
    return f"BUG-{max(nums, default=0) + 1:03d}"


def get_all_bugs() -> list[dict]:
    """Return all bugs as a list of dicts."""
    with SessionLocal() as session:
        bugs = session.query(BugORM).all()
        return [_bug_to_dict(b) for b in bugs]


def get_bug(bug_id: str) -> dict | None:
    """Return a single bug by ID or None if not found."""
    with SessionLocal() as session:
        bug = session.query(BugORM).filter(BugORM.id == bug_id).first()
        return _bug_to_dict(bug) if bug is not None else None


def find_bug_by_signature(failure_message: str) -> dict | None:
    """Find a bug whose failure_signatures contains a substring present in
    failure_message (case-insensitive). Also matches if the bug's ID appears
    as a substring in failure_message (e.g. 'BUG-001' in message)."""
    lower_msg = failure_message.lower()
    with SessionLocal() as session:
        bugs = session.query(BugORM).all()
        for bug in bugs:
            for sig in (bug.failure_signatures or []):
                if sig.lower() in lower_msg:
                    return _bug_to_dict(bug)
            if bug.id.lower() in lower_msg:
                return _bug_to_dict(bug)
    return None


def create_bug(
    title: str,
    severity: str,
    feature: str | None,
    failure_signature: str,
    build: str,
    test_name: str,
) -> dict:
    """Create a new bug with auto-assigned ID.
    Status: open. Escaped: False."""
    with SessionLocal() as session:
        new_id = _next_id(session)
        new_bug = BugORM(
            id=new_id,
            title=title,
            status="open",
            severity=severity,
            feature=feature,
            escaped=False,
            failure_signatures=[failure_signature],
            linked_builds=[build],
            linked_test_names=[test_name],
        )
        session.add(new_bug)
        session.commit()
        session.refresh(new_bug)
        result = _bug_to_dict(new_bug)

    logger.info("bug_created", extra={"bug_id": new_id, "title": title, "feature": feature})
    return result


def link_failure_to_bug(bug_id: str, build: str, test_name: str) -> dict | None:
    """Add build and test_name to existing bug if not already present.
    Never modifies status."""
    with SessionLocal() as session:
        bug = session.query(BugORM).filter(BugORM.id == bug_id).first()
        if bug is None:
            return None
        builds = list(bug.linked_builds or [])
        tests = list(bug.linked_test_names or [])
        changed = False
        if build not in builds:
            builds.append(build)
            changed = True
        if test_name not in tests:
            tests.append(test_name)
            changed = True
        if changed:
            bug.linked_builds = builds
            bug.linked_test_names = tests
            session.commit()
        result = _bug_to_dict(bug)

    logger.info("bug_linked", extra={"bug_id": bug_id, "build": build, "test_name": test_name})
    return result


def set_bug_status(bug_id: str, status: str) -> dict | None:
    """Set bug status to open, resolved, or verified."""
    with SessionLocal() as session:
        bug = session.query(BugORM).filter(BugORM.id == bug_id).first()
        if bug is None:
            return None
        bug.status = status
        session.commit()
        result = _bug_to_dict(bug)

    logger.info("bug_status_updated", extra={"bug_id": bug_id, "status": status})
    return result


def get_bugs_for_feature(feature: str) -> list[dict]:
    """Return all bugs for a given feature."""
    with SessionLocal() as session:
        bugs = session.query(BugORM).filter(BugORM.feature == feature).all()
        return [_bug_to_dict(b) for b in bugs]


def _seed_from_data(seed_data: dict) -> None:
    """Seed bugs table from seed_data dict."""
    bugs = seed_data.get("bugs", [])
    bug_feature_edges = {}
    for edge in seed_data.get("bug_feature_edges", []):
        if edge["bug_id"] not in bug_feature_edges:
            bug_feature_edges[edge["bug_id"]] = edge["feature"]
    with SessionLocal() as session:
        for bug in bugs:
            status = "open" if bug.get("escaped") else "resolved"
            feature = bug_feature_edges.get(bug["id"])
            session.merge(BugORM(
                id=bug["id"],
                title=bug["title"],
                severity=bug["severity"],
                status=status,
                feature=feature,
                escaped=bug.get("escaped", False),
                failure_signatures=[],
                linked_builds=[],
                linked_test_names=[],
            ))
        session.commit()
    logger.info("bug_store_loaded", extra={
        "bug_count": len(bugs),
        "source": "seed_data.json",
    })


def reset_store() -> None:
    """Delete all bugs and re-seed from demo/data/seed_data.json."""
    seed_path = Path(__file__).parent.parent / "demo" / "data" / "seed_data.json"
    with SessionLocal() as session:
        session.query(BugORM).delete()
        session.commit()
    if seed_path.exists():
        with open(seed_path) as f:
            seed_data = json.load(f)
        _seed_from_data(seed_data)
    logger.info("bug_store_reset")


def load_bugs() -> None:
    """Seed the bugs table from demo/data/seed_data.json if table is empty."""
    seed_path = Path(__file__).parent.parent / "demo" / "data" / "seed_data.json"
    with SessionLocal() as session:
        count = session.query(BugORM).count()
    if count > 0:
        logger.info("bug_store_loaded", extra={"bug_count": count, "source": "postgres"})
        return
    if not seed_path.exists():
        logger.warning("seed_data_not_found", extra={"path": str(seed_path)})
        return
    with open(seed_path) as f:
        seed_data = json.load(f)
    _seed_from_data(seed_data)


# Initialise table and seed on import
init_db()
load_bugs()
