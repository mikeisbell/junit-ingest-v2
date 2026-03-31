# JUnit XML Ingestion Service - Phase 4

## Overview

Replace the in-memory results store with a PostgreSQL database using SQLAlchemy.

## Context

- Existing FastAPI service is in app/main.py
- Existing Pydantic models are in app/models.py
- In-memory store is a module-level list called results_store in app/main.py
- Docker Compose already exists and runs the API service

## Tech Stack Additions

- PostgreSQL 15
- SQLAlchemy 2.0 for ORM
- psycopg2-binary as the Postgres driver

## Functional Requirements

- Add a PostgreSQL service to docker-compose.yml
- Create a database.py module in app/ that sets up SQLAlchemy engine and session
- Create a db_models.py module in app/ that defines the SQLAlchemy ORM models for:
  - TestSuiteResult (name, total_tests, total_failures, total_errors, total_skipped, elapsed_time)
  - TestCase (name, status, failure_message, foreign key to TestSuiteResult)
- Replace the in-memory results_store with database writes on POST /results
- GET /results should return all results from the database
- GET /results/{index} should return a single result by its database ID, not list position
- Create tables automatically on startup using SQLAlchemy create_all
- Use environment variables for database connection string with a sensible default

## What Good Output Looks Like

- Clean separation between API layer, database session, and ORM models
- No raw SQL — use SQLAlchemy ORM
- Database connection string read from environment variable DATABASE_URL
- docker-compose.yml includes postgres service with correct environment variables
- API service depends_on postgres in docker-compose.yml
