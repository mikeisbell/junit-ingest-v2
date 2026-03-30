#!/usr/bin/env python3
"""Seed the Neo4j knowledge graph with demo data.

Run this script once after starting the Docker stack to populate the graph
with realistic nodes and relationships for the demo environment.

Usage:
    python demo/seed.py

Environment variables required:
    NEO4J_URI      (default: bolt://localhost:7687)
    NEO4J_USER     (default: neo4j)
    NEO4J_PASSWORD (default: devrev_demo)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.graph import get_driver, init_graph, seed_graph

SEED_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "seed_data.json")


def main():
    with open(SEED_DATA_PATH) as f:
        seed_data = json.load(f)

    driver = get_driver()
    if driver is None:
        print("ERROR: Could not connect to Neo4j. Is the stack running?")
        sys.exit(1)

    init_graph(driver)
    seed_graph(driver, seed_data)
    driver.close()
    print("Demo graph seeded successfully.")

    from bug_tracker import reset_store, link_failure_to_bug
    reset_store()
    link_failure_to_bug('BUG-001', 'build-prev', 'test_cart_persistence_across_sessions')
    link_failure_to_bug('BUG-003', 'build-prev', 'test_payment_gateway')
    link_failure_to_bug('BUG-003', 'build-prev', 'test_legacy_payment_flow')
    link_failure_to_bug('BUG-004', 'build-prev', 'test_order_processing')
    print("Bug tracker seeded successfully.")


if __name__ == "__main__":
    main()
