"""Unit tests for app/graph/seed.py.

All tests use mocked Neo4j drivers and sessions. No live Neo4j instance required.
"""
import pytest
from unittest.mock import MagicMock

from app.graph.seed import seed_graph


# ─── shared helpers ───────────────────────────────────────────────────────────


def make_mock_driver():
    """Return a (mock_driver, mock_session) pair wired for context-manager use."""
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    return mock_driver, mock_session


@pytest.fixture
def full_seed_data():
    """Full seed data dict covering all five node and edge types."""
    return {
        "modules": [{"name": "cart.py", "path": "src/cart.py"}],
        "features": [{"name": "checkout", "description": "Handles checkout flow"}],
        "feature_module_edges": [{"feature": "checkout", "module": "cart.py"}],
        "bugs": [{"id": "BUG-001", "title": "Cart crash", "severity": "high", "escaped": True}],
        "bug_feature_edges": [{"bug_id": "BUG-001", "feature": "checkout"}],
    }


# ─── tests ────────────────────────────────────────────────────────────────────


def test_seed_graph_runs_all_five_node_and_edge_types(full_seed_data):
    """seed_graph with full data should produce exactly 5 session.run calls:
    one module, one feature, one feature_module_edge, one bug, one bug_feature_edge."""
    mock_driver, mock_session = make_mock_driver()
    seed_graph(mock_driver, full_seed_data)
    assert mock_session.run.call_count == 5


def test_seed_graph_creates_codemodule_node(full_seed_data):
    """At least one session.run call must reference 'CodeModule' to create the module node."""
    mock_driver, mock_session = make_mock_driver()
    seed_graph(mock_driver, full_seed_data)
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    assert any("CodeModule" in q for q in queries)


def test_seed_graph_creates_feature_node(full_seed_data):
    """At least one session.run call must reference 'Feature' to create the feature node."""
    mock_driver, mock_session = make_mock_driver()
    seed_graph(mock_driver, full_seed_data)
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    assert any("Feature" in q for q in queries)


def test_seed_graph_creates_implemented_in_relationship(full_seed_data):
    """At least one session.run call must create the IMPLEMENTED_IN relationship."""
    mock_driver, mock_session = make_mock_driver()
    seed_graph(mock_driver, full_seed_data)
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    assert any("IMPLEMENTED_IN" in q for q in queries)


def test_seed_graph_creates_bug_node(full_seed_data):
    """At least one session.run call must reference 'Bug' to create the bug node."""
    mock_driver, mock_session = make_mock_driver()
    seed_graph(mock_driver, full_seed_data)
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    assert any("Bug" in q for q in queries)


def test_seed_graph_creates_affects_relationship(full_seed_data):
    """At least one session.run call must create the AFFECTS relationship."""
    mock_driver, mock_session = make_mock_driver()
    seed_graph(mock_driver, full_seed_data)
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    assert any("AFFECTS" in q for q in queries)


def test_seed_graph_uses_merge_not_bare_create(full_seed_data):
    """Every session.run query that contains CREATE must also contain MERGE.
    This verifies idempotency: no bare CREATE statements are allowed in seed_graph."""
    mock_driver, mock_session = make_mock_driver()
    seed_graph(mock_driver, full_seed_data)
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    for q in queries:
        if "CREATE" in q:
            assert "MERGE" in q, f"Bare CREATE found without MERGE in query: {q}"


def test_seed_graph_handles_empty_seed_data():
    """An empty dict should trigger no session.run calls and raise no exceptions."""
    mock_driver, mock_session = make_mock_driver()
    seed_graph(mock_driver, {})
    assert mock_session.run.call_count == 0


def test_seed_graph_handles_partial_seed_data_modules_only():
    """Seed data with only a modules list should call session.run once for the module node
    and must not issue any Feature, Bug, IMPLEMENTED_IN, or AFFECTS queries."""
    mock_driver, mock_session = make_mock_driver()
    seed_graph(mock_driver, {"modules": [{"name": "cart.py", "path": "src/cart.py"}]})
    assert mock_session.run.call_count == 1
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    assert not any("Feature" in q for q in queries)
    assert not any("Bug" in q for q in queries)
    assert not any("IMPLEMENTED_IN" in q for q in queries)
    assert not any("AFFECTS" in q for q in queries)


def test_seed_graph_handles_multiple_modules():
    """Seed data with three modules should call session.run exactly 3 times."""
    mock_driver, mock_session = make_mock_driver()
    seed_graph(mock_driver, {
        "modules": [
            {"name": "cart.py", "path": "src/cart.py"},
            {"name": "auth.py", "path": "src/auth.py"},
            {"name": "payment.py", "path": "src/payment.py"},
        ]
    })
    assert mock_session.run.call_count == 3
