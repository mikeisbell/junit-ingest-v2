"""Neo4j schema initialization for the knowledge graph layer.

This module creates uniqueness constraints on core node types at startup.
Constraints prevent duplicate nodes under concurrent MERGE operations and
make graph queries more efficient by enforcing indexed lookups on the
constrained properties.
"""
import logging

from ..logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)


def init_graph(driver) -> None:
    """Create uniqueness constraints on core node types.

    Uses CREATE CONSTRAINT IF NOT EXISTS so it is safe to call on every startup.
    Constraints prevent duplicate nodes from being created under concurrent MERGE
    operations in ingest_suite_to_graph and seed_graph.

    Args:
        driver: A connected neo4j.Driver instance. Must not be None.
    """
    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (t:TestCase) REQUIRE t.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (f:Feature) REQUIRE f.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:CodeModule) REQUIRE c.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (b:Bug) REQUIRE b.id IS UNIQUE",
    ]
    with driver.session() as session:
        for cypher in constraints:
            session.run(cypher)
    logger.info("neo4j_constraints_initialized")
