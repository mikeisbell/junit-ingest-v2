"""Tests for the bug_tracker module."""
import pytest

pytestmark = pytest.mark.integration

import bug_tracker as bt


@pytest.fixture(autouse=True)
def clean_bugs():
    """Reset the bug store before and after each test for isolation."""
    bt.reset_store()
    yield
    bt.reset_store()


# 1. load_bugs populates the store from seed data with correct defaults
def test_load_bugs_populates_from_seed():
    bugs = bt.get_all_bugs()
    assert len(bugs) > 0
    for bug in bugs:
        assert "id" in bug
        assert "title" in bug
        assert "status" in bug
        assert "severity" in bug
        assert "failure_signatures" in bug
        assert "linked_builds" in bug
        assert "linked_test_names" in bug
        assert "escaped" in bug


def test_load_bugs_applies_status_defaults():
    bugs = {b["id"]: b for b in bt.get_all_bugs()}
    # BUG-001 has escaped=True -> status "open"
    assert bugs["BUG-001"]["status"] == "open"
    # BUG-003 has escaped=False -> status "resolved"
    assert bugs["BUG-003"]["status"] == "resolved"


def test_load_bugs_applies_feature_edges():
    bugs = {b["id"]: b for b in bt.get_all_bugs()}
    # First bug_feature_edge for BUG-001 is "checkout_flow"
    assert bugs["BUG-001"]["feature"] == "checkout_flow"
    assert bugs["BUG-002"]["feature"] == "user_profile"


# 2. get_all_bugs returns all bugs
def test_get_all_bugs_returns_all():
    bugs = bt.get_all_bugs()
    # seed_data has 4 bugs
    assert len(bugs) == 4


# 3. get_bug returns correct bug by ID
def test_get_bug_returns_correct_bug():
    bug = bt.get_bug("BUG-001")
    assert bug is not None
    assert bug["id"] == "BUG-001"
    assert bug["title"] == "Checkout fails when cart has more than 10 items"


# 4. get_bug returns None for unknown ID
def test_get_bug_unknown_id_returns_none():
    assert bt.get_bug("BUG-999") is None


# 5. find_bug_by_signature matches a substring (case-insensitive)
def test_find_bug_by_signature_matches():
    bt.create_bug(
        title="Crash on login",
        severity="high",
        feature="user_profile",
        failure_signature="NullPointerException in LoginHandler",
        build="build-1",
        test_name="test_login",
    )
    result = bt.find_bug_by_signature("Got a nullpointerexception in loginhandler during test")
    assert result is not None
    assert result["title"] == "Crash on login"


# 6. find_bug_by_signature returns None when no match
def test_find_bug_by_signature_no_match():
    assert bt.find_bug_by_signature("totally unrelated error message") is None


# 7. create_bug returns a bug with correct fields and auto-assigned ID
def test_create_bug_returns_correct_fields():
    bug = bt.create_bug(
        title="New bug",
        severity="medium",
        feature="shopping_cart",
        failure_signature="IndexError in CartService",
        build="build-42",
        test_name="test_cart_add",
    )
    assert bug["title"] == "New bug"
    assert bug["severity"] == "medium"
    assert bug["feature"] == "shopping_cart"
    assert bug["failure_signatures"] == ["IndexError in CartService"]
    assert bug["linked_builds"] == ["build-42"]
    assert bug["linked_test_names"] == ["test_cart_add"]
    assert bug["status"] == "open"
    assert bug["escaped"] is False
    # ID should be auto-assigned beyond the seeded bugs (BUG-001..BUG-004)
    assert bug["id"].startswith("BUG-")
    assert int(bug["id"][4:]) >= 5


# 8. create_bug persists to postgres
def test_create_bug_persists_to_postgres():
    """Create a bug and verify it is retrievable from the database."""
    created = bt.create_bug(
        title="Persisted bug",
        severity="low",
        feature=None,
        failure_signature="timeout",
        build="build-99",
        test_name="test_timeout",
    )
    bug_id = created["id"]

    assert bt.get_bug(bug_id) is not None
    assert bt.get_bug(bug_id)["title"] == "Persisted bug"


# 9. link_failure_to_bug adds build and test_name without duplicates
def test_link_failure_to_bug_no_duplicates():
    bug = bt.create_bug(
        title="Existing bug",
        severity="high",
        feature=None,
        failure_signature="some error",
        build="build-1",
        test_name="test_a",
    )
    bug_id = bug["id"]

    # Link same values again
    updated = bt.link_failure_to_bug(bug_id, "build-1", "test_a")
    assert updated["linked_builds"].count("build-1") == 1
    assert updated["linked_test_names"].count("test_a") == 1

    # Link new values
    updated = bt.link_failure_to_bug(bug_id, "build-2", "test_b")
    assert "build-2" in updated["linked_builds"]
    assert "test_b" in updated["linked_test_names"]


def test_link_failure_to_bug_unknown_id_returns_none():
    assert bt.link_failure_to_bug("BUG-999", "build-1", "test_x") is None


# 10. set_bug_status updates status correctly
def test_set_bug_status_updates():
    bug = bt.get_bug("BUG-003")
    assert bug["status"] == "resolved"

    updated = bt.set_bug_status("BUG-003", "verified")
    assert updated["status"] == "verified"

    # Confirm database is updated
    assert bt.get_bug("BUG-003")["status"] == "verified"


def test_set_bug_status_unknown_id_returns_none():
    assert bt.set_bug_status("BUG-999", "open") is None


# 11. get_bugs_for_feature returns only bugs matching the feature
def test_get_bugs_for_feature():
    results = bt.get_bugs_for_feature("checkout_flow")
    assert all(b["feature"] == "checkout_flow" for b in results)
    assert any(b["id"] == "BUG-001" for b in results)

    results_empty = bt.get_bugs_for_feature("nonexistent_feature")
    assert results_empty == []
