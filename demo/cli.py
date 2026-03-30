"""AI Test Pipeline — Demo CLI

Inject fake artifacts into the live AI test pipeline and observe real responses.
All state persists to demo/data/session.json.

Usage (from project root):
    python demo/cli.py status
    python demo/cli.py mr submit --mr-id MR-42 --author alice --modules cart_service
    python demo/cli.py build submit --build-id build-47 --xml demo/data/demo.xml
    python demo/cli.py bug list
    python demo/cli.py reset --confirm
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# ANSI color helpers
# ---------------------------------------------------------------------------

RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[36m"
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
DIM    = "\033[2m"
WHITE  = "\033[37m"


def hdr(text):
    print(f"\n{BOLD}{CYAN}{text}{RESET}")


def ok(text):
    print(f"{GREEN}  ✓  {text}{RESET}")


def err(text):
    print(f"{RED}  ✗  {text}{RESET}")


def info(text):
    print(f"{YELLOW}  ▶  {text}{RESET}")


def detail(label, value):
    print(f"{DIM}     {label}:{RESET} {value}")


def section(text):
    print(f"\n{BOLD}  {text}{RESET}")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVICE_URL = os.getenv("SERVICE_URL", "http://localhost:8001")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
DEMO_DIR = Path(__file__).parent
DATA_DIR = DEMO_DIR / "data"
SESSION_FILE = DATA_DIR / "session.json"

# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


def load_session() -> dict:
    """Load session from disk or return empty session dict."""
    if SESSION_FILE.exists():
        try:
            with open(SESSION_FILE, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            pass
    return {"api_key": None, "mrs": {}, "builds": {}}


def save_session(session: dict) -> None:
    """Persist session to SESSION_FILE."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SESSION_FILE, "w", encoding="utf-8") as fh:
        json.dump(session, fh, indent=2)


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------


def api(method, path, *, api_key="", data=None, files=None, params=None) -> dict:
    """Make an HTTP request to the service and return parsed JSON.

    - params: dict of query string parameters
    - data: dict to JSON-encode as request body
    - files: dict {"file": (filename, bytes)} for multipart upload
    - api_key: if set, adds Authorization: Bearer {api_key} header

    Raises RuntimeError with response body on non-2xx status.
    """
    url = SERVICE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    if files is not None:
        boundary = "----DemoCLIBoundary7MA4YWxkTrZu0gW"
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        body = b""
        for field_name, (filename, file_bytes) in files.items():
            part_header = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
            )
            body += part_header.encode() + file_bytes + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req_body = body
    elif data is not None:
        req_body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    else:
        req_body = None

    req = urllib.request.Request(url, data=req_body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {body}") from exc


# ---------------------------------------------------------------------------
# API key management
# ---------------------------------------------------------------------------


def ensure_api_key(session: dict) -> str:
    """Return the stored API key or create a new one."""
    existing = session.get("api_key")
    if existing:
        # Verify it still works
        try:
            urllib.request.urlopen(
                urllib.request.Request(
                    f"{SERVICE_URL}/health",
                    headers={"Authorization": f"Bearer {existing}"},
                    method="GET",
                )
            )
            return existing
        except urllib.error.HTTPError:
            pass  # Key invalid — fall through to create a new one

    if not ADMIN_TOKEN:
        err("ADMIN_TOKEN environment variable not set and no cached API key found.")
        sys.exit(1)

    resp = api(
        "POST",
        "/keys",
        data={"name": "demo-cli"},
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    key = resp["key"]
    session["api_key"] = key
    save_session(session)
    ok("API key created: demo-cli")
    return key


# Patch api() to support extra headers not covered by api_key
def _api_with_headers(method, path, *, api_key="", data=None, files=None,
                      params=None, headers=None) -> dict:
    """Internal version of api() that accepts arbitrary extra headers."""
    url = SERVICE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)

    req_headers = dict(headers or {})
    if api_key:
        req_headers["Authorization"] = f"Bearer {api_key}"

    if files is not None:
        boundary = "----DemoCLIBoundary7MA4YWxkTrZu0gW"
        req_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        body = b""
        for field_name, (filename, file_bytes) in files.items():
            part_header = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
            )
            body += part_header.encode() + file_bytes + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req_body = body
    elif data is not None:
        req_body = json.dumps(data).encode()
        req_headers.setdefault("Content-Type", "application/json")
    else:
        req_body = None

    req = urllib.request.Request(
        url, data=req_body, headers=req_headers, method=method
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {body}") from exc


# Replace api() reference used for /keys with the full version
def _create_key_with_admin_token() -> dict:
    return _api_with_headers(
        "POST",
        "/keys",
        data={"name": "demo-cli"},
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )


def ensure_api_key(session: dict) -> str:  # noqa: F811
    """Return the stored API key or create a new one."""
    existing = session.get("api_key")
    if existing:
        try:
            urllib.request.urlopen(
                urllib.request.Request(
                    f"{SERVICE_URL}/health",
                    headers={"Authorization": f"Bearer {existing}"},
                    method="GET",
                )
            )
            return existing
        except (urllib.error.HTTPError, urllib.error.URLError):
            pass  # Key invalid or service down — fall through

    if not ADMIN_TOKEN:
        err("ADMIN_TOKEN environment variable not set and no cached API key found.")
        sys.exit(1)

    resp = _create_key_with_admin_token()
    key = resp["key"]
    session["api_key"] = key
    save_session(session)
    ok("API key created: demo-cli")
    return key


# ---------------------------------------------------------------------------
# Command: status
# ---------------------------------------------------------------------------


def cmd_status():
    hdr("Service Health")
    try:
        resp = api("GET", "/health")
    except RuntimeError as exc:
        err(str(exc))
        sys.exit(1)

    all_ok = True
    for dep in ("postgres", "chromadb", "redis", "neo4j"):
        status = resp.get("dependencies", {}).get(dep, {}).get("status", "unknown")
        if status == "ok":
            ok(f"{dep}: {status}")
        else:
            err(f"{dep}: {status}")
            all_ok = False

    print()
    if all_ok:
        ok("All systems operational")
    else:
        err("One or more dependencies degraded")


# ---------------------------------------------------------------------------
# Command group: mr
# ---------------------------------------------------------------------------


def cmd_mr_submit(args, session, api_key):
    hdr(f"Submitting MR: {args.mr_id}")
    detail("Author", args.author)
    detail("Changed modules", ", ".join(args.modules))
    detail("Outcome setting", args.outcome)

    fixture_file = (
        DATA_DIR / "premerge_fixtures.json"
        if args.outcome == "fail"
        else DATA_DIR / "premerge_fixtures_passing.json"
    )
    if fixture_file.exists():
        info(f"Loaded fixture: {fixture_file.name}")
    else:
        info(f"Fixture file not found, proceeding: {fixture_file.name}")

    response = api(
        "POST",
        "/webhook/premerge",
        api_key=api_key,
        data={
            "mr_id": args.mr_id,
            "author": args.author,
            "changed_modules": args.modules,
            "description": args.description,
            "outcome": args.outcome,
        },
    )

    section("Test Selection  (Neo4j Knowledge Graph)")
    detail("Tests selected", response.get("total_selected"))
    detail("Build", response.get("build"))

    section("Simulated Execution")
    for r in response.get("results", []):
        if r["status"] == "passed":
            ok(r["test_name"])
        else:
            err(r["test_name"])
            msg = r.get("failure_message") or ""
            if msg:
                detail("  failure", msg[:120])

    section("Failed Tests")
    failures = response.get("failures") or []
    if failures:
        for item in failures:
            err(item["test_name"])
            detail("  reason", (item.get("failure_message") or "")[:120])
    else:
        ok("No failures — all tests passed")

    section("Merge Decision")
    if response.get("merge_recommendation") == "approved":
        ok("MERGE APPROVED")
    else:
        err("MERGE BLOCKED — resolve failures before merging")

    session["mrs"][args.mr_id] = {
        "mr_id": args.mr_id,
        "author": args.author,
        "modules": args.modules,
        "outcome": args.outcome,
        "merge_recommendation": response.get("merge_recommendation"),
        "submitted_at": datetime.utcnow().isoformat(),
        "response": response,
    }


def cmd_mr_list(session):
    hdr("MRs This Session")
    mrs = session.get("mrs", {})
    if not mrs:
        info("No MRs submitted this session.")
        return

    for mr in mrs.values():
        rec = mr.get("merge_recommendation", "")
        modules = ", ".join(mr.get("modules", []))
        ts = mr.get("submitted_at", "")[:19]
        line = f"  {mr['mr_id']:<10} {mr['author']:<12} {modules:<30} {rec.upper():<10} {ts}"
        if rec == "approved":
            ok(line.strip())
        else:
            err(line.strip())


def cmd_mr_show(args, session):
    hdr(f"MR Details: {args.mr_id}")
    mr = session.get("mrs", {}).get(args.mr_id)
    if not mr:
        err(f"MR {args.mr_id} not found in session.")
        sys.exit(1)

    detail("Author", mr["author"])
    detail("Modules", ", ".join(mr.get("modules", [])))
    detail("Outcome", mr["outcome"])
    detail("Merge recommendation", mr["merge_recommendation"])
    detail("Submitted at", mr["submitted_at"])
    section("Pipeline Response")
    print(json.dumps(mr["response"], indent=2))


# ---------------------------------------------------------------------------
# Command group: build
# ---------------------------------------------------------------------------


def cmd_build_submit(args, session, api_key):
    hdr(f"Submitting Build: {args.build_id}")
    detail("XML file", args.xml)
    detail("Triggered by", args.triggered_by or "manual")

    xml_path = Path(args.xml)
    if not xml_path.exists():
        err(f"XML file not found: {args.xml}")
        sys.exit(1)

    with open(xml_path, "rb") as fh:
        xml_bytes = fh.read()

    response = api(
        "POST",
        f"/webhook/analyze?build={args.build_id}",
        api_key=api_key,
        files={"file": (xml_path.name, xml_bytes)},
    )

    section("Regression Results")
    detail("Suite", response.get("suite_name"))
    detail("Total tests", response.get("total_tests"))
    detail("Passed", response.get("total_passed"))
    detail("Failed", response.get("total_failures"))
    failure_rate = response.get("failure_rate", 0)
    detail("Failure rate", f"{failure_rate:.0%}")

    if response.get("analysis"):
        section("Failure Analysis")
        detail("Bugs linked", response["analysis"]["bugs_linked"])
        detail("New bugs created", response["analysis"]["bugs_created"])
        detail("Bug IDs", ", ".join(response["analysis"]["bug_ids"]))

    section("Bug Lifecycle — Verified Resolution")
    if response.get("verified_bugs"):
        for bug_id in response["verified_bugs"]:
            ok(f"{bug_id} promoted to Verified")
    else:
        info("No bugs promoted to Verified in this run")

    section("Build Decision")
    if response.get("merge_recommendation") == "approved":
        ok("BUILD PASSED — no new failures")
    else:
        err("BUILD FAILED — new failures detected")

    session["builds"][args.build_id] = {
        "build_id": args.build_id,
        "xml": args.xml,
        "triggered_by": args.triggered_by,
        "submitted_at": datetime.utcnow().isoformat(),
        "response": response,
    }


def cmd_build_list(session):
    hdr("Builds This Session")
    builds = session.get("builds", {})
    if not builds:
        info("No builds submitted this session.")
        return

    for b in builds.values():
        rec = b.get("response", {}).get("merge_recommendation", "")
        ts = b.get("submitted_at", "")[:19]
        triggered = b.get("triggered_by") or "manual"
        line = f"  {b['build_id']:<15} {triggered:<20} {rec.upper():<10} {ts}"
        if rec == "approved":
            ok(line.strip())
        else:
            err(line.strip())


def cmd_build_show(args, session):
    hdr(f"Build Details: {args.build_id}")
    b = session.get("builds", {}).get(args.build_id)
    if not b:
        err(f"Build {args.build_id} not found in session.")
        sys.exit(1)

    detail("XML", b["xml"])
    detail("Triggered by", b.get("triggered_by") or "manual")
    detail("Submitted at", b["submitted_at"])
    section("Pipeline Response")
    print(json.dumps(b["response"], indent=2))


# ---------------------------------------------------------------------------
# Command group: bug
# ---------------------------------------------------------------------------


def cmd_bug_list():
    from app.bug_tracker import get_all_bugs

    hdr("Bug Tracker")
    bugs = get_all_bugs()
    if not bugs:
        info("No bugs in tracker.")
        return

    for bug in bugs:
        bug_id = bug.get("id", "")
        severity = (bug.get("severity") or "").upper()[:5].ljust(5)
        status = bug.get("status", "open")
        feature = bug.get("feature") or ""
        title = bug.get("title", "")[:60]

        if status == "open":
            color = RED
        elif status == "resolved":
            color = YELLOW
        else:
            color = GREEN

        print(
            f"  {BOLD}{bug_id:<10}{RESET} "
            f"[{severity}]  "
            f"{color}{status:<10}{RESET} "
            f"{feature:<20} "
            f"{DIM}{title}{RESET}"
        )


def cmd_bug_show(args):
    from app.bug_tracker import get_bug

    hdr(f"Bug: {args.bug_id}")
    bug = get_bug(args.bug_id)
    if not bug:
        err(f"Bug {args.bug_id} not found.")
        sys.exit(1)

    for key, val in bug.items():
        if isinstance(val, list):
            detail(key, ", ".join(str(v) for v in val) if val else "(none)")
        else:
            detail(key, val)


def cmd_bug_create(args):
    from app.bug_tracker import create_bug

    hdr("Create Bug")
    bug = create_bug(
        title=args.title,
        severity=args.severity,
        feature=args.feature or "",
        failure_signature=args.signature or "",
        build="manual",
        test_name="manual",
    )
    ok(f"Created {bug['id']}")
    for key, val in bug.items():
        detail(key, val)


def cmd_bug_update_status(args):
    from app.bug_tracker import set_bug_status

    valid = {"open", "resolved", "verified"}
    if args.status not in valid:
        err(f"Invalid status '{args.status}'. Choose from: {', '.join(sorted(valid))}")
        sys.exit(1)

    result = set_bug_status(args.bug_id, args.status)
    if result:
        ok(f"{args.bug_id} status updated to {args.status}")
    else:
        err(f"Bug {args.bug_id} not found.")


def cmd_bug_link(args):
    from app.bug_tracker import link_failure_to_bug

    hdr(f"Link failure to {args.bug_id}")
    result = link_failure_to_bug(args.bug_id, args.build, args.test_name)
    if result:
        ok(f"Linked build={args.build} test={args.test_name} to {args.bug_id}")
    else:
        err(f"Bug {args.bug_id} not found or link already exists.")


# ---------------------------------------------------------------------------
# Command group: graph
# ---------------------------------------------------------------------------


def cmd_graph_show_modules():
    from app.graph.driver import get_driver

    hdr("Code Modules")
    driver = get_driver()
    if driver is None:
        err("Neo4j unavailable.")
        sys.exit(1)

    with driver.session() as s:
        result = s.run(
            "MATCH (m:CodeModule) RETURN m.name AS name, m.path AS path ORDER BY m.name"
        )
        rows = list(result)

    if not rows:
        info("No modules found.")
        return
    for row in rows:
        detail(row["name"], row["path"] or "")


def cmd_graph_show_features():
    from app.graph.driver import get_driver

    hdr("Features → Modules")
    driver = get_driver()
    if driver is None:
        err("Neo4j unavailable.")
        sys.exit(1)

    with driver.session() as s:
        result = s.run(
            "MATCH (f:Feature)-[:IMPLEMENTED_IN]->(m:CodeModule) "
            "RETURN f.name AS feature, collect(m.name) AS modules "
            "ORDER BY f.name"
        )
        rows = list(result)

    if not rows:
        info("No features found.")
        return
    for row in rows:
        detail(row["feature"], ", ".join(row["modules"]))


def cmd_graph_show_tests(args):
    from app.graph.driver import get_driver
    from app.graph.queries import get_tests_for_modules

    hdr(f"Tests covering module: {args.module}")
    driver = get_driver()
    if driver is None:
        err("Neo4j unavailable.")
        sys.exit(1)

    tests = get_tests_for_modules(driver, [args.module])
    if not tests:
        info("No tests found for that module.")
        return
    for t in tests:
        detail(
            t.get("test_name", ""),
            f"feature={t.get('feature_name', '')}  priority={t.get('priority', '')}",
        )


def cmd_graph_gaps(args, api_key):
    hdr(f"Coverage Gap Analysis: {args.bug_id}")
    response = api("GET", f"/graph/gaps/{args.bug_id}", api_key=api_key)

    detail("Bug title", response.get("bug_title", ""))
    detail("Affected features", ", ".join(response.get("affected_features", [])))

    section("Covering Tests")
    for t in response.get("covering_tests", []):
        detail(t.get("test_name", ""), f"priority={t.get('priority', '')}")

    section("Gap Assessment")
    assessment = response.get("gap_assessment", "")
    if assessment == "covered":
        ok(f"Gap assessment: {assessment}")
    elif assessment == "gap_detected":
        err(f"Gap assessment: {assessment}")
    else:
        print(f"{YELLOW}  ▶  Gap assessment: {assessment}{RESET}")


# ---------------------------------------------------------------------------
# Command: reset
# ---------------------------------------------------------------------------


def cmd_reset(args, session):
    if not args.confirm:
        err("Add --confirm to reset demo data.")
        sys.exit(1)

    from app.bug_tracker import reset_store

    reset_store()
    session.update({"api_key": session.get("api_key"), "mrs": {}, "builds": {}})
    save_session(session)
    ok("Demo data reset to seed state.")


# ---------------------------------------------------------------------------
# argparse setup
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(
    prog="cli.py",
    description="AI Test Pipeline — Demo CLI",
)
parser.add_argument("--service-url", default=SERVICE_URL)

subparsers = parser.add_subparsers(dest="group", required=True)

# --- status ---
subparsers.add_parser("status", help="Check service health")

# --- reset ---
reset_p = subparsers.add_parser("reset", help="Reset demo data to seed state")
reset_p.add_argument("--confirm", action="store_true")

# --- mr ---
mr_parser = subparsers.add_parser("mr", help="MR commands")
mr_sub = mr_parser.add_subparsers(dest="command", required=True)

mr_submit = mr_sub.add_parser("submit", help="Submit a fake MR")
mr_submit.add_argument("--mr-id", required=True)
mr_submit.add_argument("--author", required=True)
mr_submit.add_argument("--modules", nargs="+", required=True)
mr_submit.add_argument("--outcome", choices=["fail", "pass"], default="fail")
mr_submit.add_argument("--description", default="")

mr_list = mr_sub.add_parser("list", help="List MRs submitted this session")
mr_show = mr_sub.add_parser("show", help="Show MR details")
mr_show.add_argument("--mr-id", required=True)

# --- build ---
build_parser = subparsers.add_parser("build", help="Build commands")
build_sub = build_parser.add_subparsers(dest="command", required=True)

build_submit = build_sub.add_parser("submit", help="Submit a fake build result")
build_submit.add_argument("--build-id", required=True)
build_submit.add_argument("--xml", required=True)
build_submit.add_argument("--triggered-by", default=None)

build_list = build_sub.add_parser("list", help="List builds submitted this session")
build_show = build_sub.add_parser("show", help="Show build details")
build_show.add_argument("--build-id", required=True)

# --- bug ---
bug_parser = subparsers.add_parser("bug", help="Bug tracker commands")
bug_sub = bug_parser.add_subparsers(dest="command", required=True)

bug_sub.add_parser("list", help="List all bugs")

bug_show_p = bug_sub.add_parser("show", help="Show bug details")
bug_show_p.add_argument("--bug-id", required=True)

bug_create_p = bug_sub.add_parser("create", help="Create a bug")
bug_create_p.add_argument("--title", required=True)
bug_create_p.add_argument("--severity", required=True)
bug_create_p.add_argument("--feature", default=None)
bug_create_p.add_argument("--signature", default=None)

bug_update_p = bug_sub.add_parser("update-status", help="Update bug status")
bug_update_p.add_argument("--bug-id", required=True)
bug_update_p.add_argument("--status", required=True)

bug_link_p = bug_sub.add_parser("link", help="Link a build/test to a bug")
bug_link_p.add_argument("--bug-id", required=True)
bug_link_p.add_argument("--build", required=True)
bug_link_p.add_argument("--test-name", required=True)

# --- graph ---
graph_parser = subparsers.add_parser("graph", help="Graph query commands")
graph_sub = graph_parser.add_subparsers(dest="command", required=True)

graph_sub.add_parser("show-modules", help="List all code modules")
graph_sub.add_parser("show-features", help="List features and their modules")

graph_tests_p = graph_sub.add_parser("show-tests", help="List tests for a module")
graph_tests_p.add_argument("--module", required=True)

graph_gaps_p = graph_sub.add_parser("gaps", help="Coverage gap analysis for a bug")
graph_gaps_p.add_argument("--bug-id", required=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    args = parser.parse_args()

    # Update SERVICE_URL if overridden on command line
    global SERVICE_URL
    if hasattr(args, "service_url") and args.service_url != SERVICE_URL:
        SERVICE_URL = args.service_url

    session = load_session()
    api_key = ""

    auth_required = not (
        args.group == "status"
        or args.group == "reset"
        or args.group == "bug"
        or (
            args.group == "graph"
            and getattr(args, "command", None)
            in ("show-modules", "show-features", "show-tests")
        )
    )
    if auth_required:
        api_key = ensure_api_key(session)

    try:
        if args.group == "status":
            cmd_status()

        elif args.group == "mr":
            if args.command == "submit":
                cmd_mr_submit(args, session, api_key)
            elif args.command == "list":
                cmd_mr_list(session)
            elif args.command == "show":
                cmd_mr_show(args, session)

        elif args.group == "build":
            if args.command == "submit":
                cmd_build_submit(args, session, api_key)
            elif args.command == "list":
                cmd_build_list(session)
            elif args.command == "show":
                cmd_build_show(args, session)

        elif args.group == "bug":
            if args.command == "list":
                cmd_bug_list()
            elif args.command == "show":
                cmd_bug_show(args)
            elif args.command == "create":
                cmd_bug_create(args)
            elif args.command == "update-status":
                cmd_bug_update_status(args)
            elif args.command == "link":
                cmd_bug_link(args)

        elif args.group == "graph":
            if args.command == "show-modules":
                cmd_graph_show_modules()
            elif args.command == "show-features":
                cmd_graph_show_features()
            elif args.command == "show-tests":
                cmd_graph_show_tests(args)
            elif args.command == "gaps":
                cmd_graph_gaps(args, api_key)

        elif args.group == "reset":
            cmd_reset(args, session)

    except RuntimeError as exc:
        err(str(exc))
        sys.exit(1)
    except Exception as exc:
        err(f"Unexpected error: {exc}")
        sys.exit(1)

    save_session(session)


if __name__ == "__main__":
    main()
