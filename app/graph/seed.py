"""Graph seeding for the Neo4j knowledge graph.

This module seeds the graph with external data passed as a parameter.
Seed data is kept outside application code so it can be changed without
modifying or redeploying the application. The demo seed data lives in
demo/data/seed_data.json; test seed data lives in tests/fixtures/seed_data.py.
All operations use MERGE so seeding is idempotent.
"""
import logging

from ..logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)


def seed_graph(driver, seed_data: dict) -> None:
    """Seed the graph with nodes and relationships from the provided seed_data dict.

    The seed_data parameter must have this structure:
        {
            "modules": [{"name": str, "path": str}],
            "features": [{"name": str, "description": str}],
            "feature_module_edges": [{"feature": str, "module": str}],
            "bugs": [{"id": str, "title": str, "severity": str, "escaped": bool}],
            "bug_feature_edges": [{"bug_id": str, "feature": str}]
        }

    The function uses MERGE for all operations so it is idempotent.
    It does not hardcode any nodes, relationships, or names.

    Args:
        driver:    A connected neo4j.Driver instance. Must not be None.
        seed_data: Dict containing all seed nodes and edges (see structure above).
    """
    with driver.session() as session:
        # --- CodeModule nodes ---
        for m in seed_data.get("modules", []):
            session.run(
                "MERGE (c:CodeModule {name: $name}) SET c.path = $path",
                name=m["name"],
                path=m["path"],
            )

        # --- Feature nodes ---
        for f in seed_data.get("features", []):
            session.run(
                "MERGE (f:Feature {name: $name}) SET f.description = $description",
                name=f["name"],
                description=f["description"],
            )

        # --- Feature IMPLEMENTED_IN CodeModule relationships ---
        for edge in seed_data.get("feature_module_edges", []):
            session.run(
                """
                MATCH (f:Feature {name: $feature}), (m:CodeModule {name: $module})
                MERGE (f)-[:IMPLEMENTED_IN]->(m)
                """,
                feature=edge["feature"],
                module=edge["module"],
            )

        # --- Bug nodes ---
        for b in seed_data.get("bugs", []):
            session.run(
                "MERGE (b:Bug {id: $id}) SET b.title = $title, b.severity = $severity, b.escaped = $escaped",
                id=b["id"],
                title=b["title"],
                severity=b["severity"],
                escaped=b["escaped"],
            )

        # --- Bug AFFECTS Feature relationships ---
        for edge in seed_data.get("bug_feature_edges", []):
            session.run(
                """
                MATCH (b:Bug {id: $bug_id}), (f:Feature {name: $feature})
                MERGE (b)-[:AFFECTS]->(f)
                """,
                bug_id=edge["bug_id"],
                feature=edge["feature"],
            )

    logger.info("neo4j_graph_seeded")
