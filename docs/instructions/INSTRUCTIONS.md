# JUnit XML Ingestion Service - Phase 1

## Overview

Build a FastAPI service that accepts a JUnit XML file upload, parses it, and returns structured results as JSON.

## Tech Stack

- Python 3.11+
- FastAPI
- pytest for testing

## Functional Requirements

- Expose a POST endpoint at /results that accepts a JUnit XML file upload
- Parse the uploaded XML file and extract the following fields:
  - Test suite name
  - Total tests
  - Total failures
  - Total errors
  - Total skipped
  - Elapsed time
  - Individual test cases including name, status (passed/failed/skipped/error), and failure message if present
- Return the parsed results as a structured JSON response
- Return a clear error message if the uploaded file is not valid JUnit XML

## What Good Output Looks Like

- Clean, readable Python code
- Pydantic models for the response structure
- Basic input validation
- A sample JUnit XML file for testing
