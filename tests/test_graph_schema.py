"""Unit tests for app/graph/schema.py.

All tests use mocked Neo4j drivers and sessions. No live Neo4j instance required.
"""
from unittest.mock import MagicMock

from app.graph.schema import init_graph


# ─── shared helpers ───────────────────────────────────────────────────────────


def make_mock_driver():
    """Return a (mock_driver, mock_session) pair wired for context-manager use."""
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    return mock_driver, mock_session


# ─── tests ────────────────────────────────────────────────────────────────────


def test_init_graph_calls_session_run_four_times():
    """init_graph must issue exactly 4 session.run calls, one per uniqueness constraint."""
    mock_driver, mock_session = make_mock_driver()
    init_graph(mock_driver)
    assert mock_session.run.call_count == 4


def test_init_graph_creates_testcase_constraint():
    """At least one constraint statement must reference the TestCase node label."""
    mock_driver, mock_session = make_mock_driver()
    init_graph(mock_driver)
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    assert any("TestCase" in q for q in queries)


def test_init_graph_creates_feature_constraint():
    """At least one constraint statement must reference the Feature node label."""
    mock_driver, mock_session = make_mock_driver()
    init_graph(mock_driver)
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    assert any("Feature" in q for q in queries)


def test_init_graph_creates_codemodule_constraint():
    """At least one constraint statement must reference the CodeModule node label."""
    mock_driver, mock_session = make_mock_driver()
    init_graph(mock_driver)
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    assert any("CodeModule" in q for q in queries)


def test_init_graph_creates_bug_constraint():
    """At least one constraint statement must reference the Bug node label."""
    mock_driver, mock_session = make_mock_driver()
    init_graph(mock_driver)
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    assert any("Bug" in q for q in queries)


def test_init_graph_uses_if_not_exists():
    """Every constraint statement must include IF NOT EXISTS to ensure idempotency on restart."""
    mock_driver, mock_session = make_mock_driver()
    init_graph(mock_driver)
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    assert all("IF NOT EXISTS" in q for q in queries)


def test_init_graph_uses_create_constraint_syntax():
    """Every constraint statement must use CREATE CONSTRAINT syntax."""
    mock_driver, mock_session = make_mock_driver()
    init_graph(mock_driver)
    queries = [call.args[0] for call in mock_session.run.call_args_list]
    assert all("CREATE CONSTRAINT" in q for q in queries)
