# Retrieval Evaluation

This directory contains the retrieval evaluation harness for the JUnit XML ingestion service.

## What it does

eval_retrieval.py runs a set of natural language queries against the live GET /search endpoint and checks whether the returned failure messages contain expected keywords. It measures whether semantic search is returning relevant results.

## How to run

1. Start the Docker stack: `docker compose up --build`
2. Ingest at least one JUnit XML file with failures via POST /results
3. Run the eval: `python tests/eval/eval_retrieval.py`

## Adding eval cases

Add new dicts to the EVAL_CASES list in eval_retrieval.py. Each case needs a query string and a list of expected_keywords to match against returned failure messages.
