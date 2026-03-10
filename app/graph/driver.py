"""Neo4j driver connection management for the knowledge graph layer.

This module is responsible for creating and verifying a Neo4j driver instance.
It reads connection parameters from environment variables and implements fail-open
behavior: if the connection cannot be established, it returns None so all graph
operations can skip gracefully without raising exceptions.
"""
import logging
import os

from neo4j import GraphDatabase

from ..logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)


def get_driver():
    """Return a Neo4j driver instance configured from environment variables.

    Reads NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD from the environment.
    Verifies connectivity immediately so misconfigurations surface at startup
    rather than at first use, when a failure would be harder to diagnose.
    Logs a warning and returns None if connection fails, enabling fail-open
    behavior: callers check for None and skip graph operations.

    Returns:
        A neo4j.Driver instance, or None if the connection cannot be established.
    """
    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "devrev_demo")
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        # Verify up-front so a misconfigured URI fails at startup rather than
        # surfacing as an obscure error in the middle of an API request.
        driver.verify_connectivity()
        return driver
    except Exception as exc:
        logger.warning("neo4j_connection_failed", extra={"error": str(exc)})
        return None
