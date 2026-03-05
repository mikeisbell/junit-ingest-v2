# JUnit XML Ingestion Service - Phase 2

## Overview

Add a GET endpoint to the existing FastAPI service that returns previously ingested test results stored in memory.

## Context

The existing POST /results endpoint parses a JUnit XML file and returns structured JSON.
The Pydantic models and parser already exist in app/models.py and app/parser.py.

## Functional Requirements

- Store each parsed TestSuiteResult in an in-memory list after a successful POST /results request
- Expose a GET endpoint at /results that returns all stored results as a JSON array
- Expose a GET endpoint at /results/{index} that returns a single result by its position in the list
- Return a clear 404 response if the index does not exist
- Do not modify the existing POST /results behavior

## What Good Output Looks Like

- Clean, readable Python code
- Reuses existing Pydantic models
- New pytest tests covering the GET endpoints
- In-memory store is simple — a module-level list is fine for now
