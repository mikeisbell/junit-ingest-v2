# JUnit XML Ingestion Service - Phase 3

## Overview

Containerize the existing FastAPI service using Docker and Docker Compose.

## Context

The existing service is a FastAPI app located in app/main.py.
Dependencies are listed in requirements.txt.
The service runs with: uvicorn app.main:app --reload

## Functional Requirements

- Create a Dockerfile that builds the FastAPI service
- Create a docker-compose.yml that runs the service
- Service should be accessible at http://localhost:8000 when running
- Hot reload is not required in the container
- The existing tests should still pass when run locally outside the container

## What Good Output Looks Like

- Dockerfile uses a slim Python base image
- Dependencies installed cleanly from requirements.txt
- docker-compose.yml is minimal and readable
- A README.md section explaining how to build and run the container
- No unnecessary layers or complexity in the Dockerfile
