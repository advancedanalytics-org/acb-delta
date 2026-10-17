---
phase: 1
title: "Backend API"
status: completed
priority: P1
effort: "2h"
dependencies: []
---

# Phase 1: Backend API

> Code for this phase was drafted before plan review (uncommitted in `backend/`). It will be adjusted to whatever this plan ends up saying.

## Overview
FastAPI service with env-driven config, Postgres/pgvector connectivity check, liveness + readiness probes, and a marked slot for the HITL router (TAI-02).

## Requirements
- Functional: `GET /health` (liveness, no deps); `GET /health/ready` (DB + pgvector + agent; 503 + per-check reason when any fails); same routes under `/api` for the frontend proxy.
- Non-functional: all config from env (`DATABASE_URL`, `AGENT_URL`, `S3_ENDPOINT`, `S3_BUCKET`, `CORS_ORIGINS`); Python 3.12, `uv.lock`; ruff clean; no tables/migrations.

## Architecture
`app/main.py` app factory → mounts `routers/health.py` at `/` and `/api`. `app/config.py` pydantic-settings singleton. `app/db.py` lazy SQLAlchemy engine (psycopg3), `ping_database()` checks `SELECT 1` + `pg_extension` has `vector`.

## Related Code Files
- Create: `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/{__init__,main,config,db}.py`, `backend/app/routers/{__init__,health}.py`, `backend/tests/test_health.py`, `backend/Dockerfile`, `backend/.dockerignore`

## Implementation Steps
1. `pyproject.toml`: fastapi, uvicorn[standard], pydantic-settings, sqlalchemy, psycopg[binary], httpx; dev group pytest, ruff; ruff + pytest config.
2. Config, db, health router, app factory as above. Comment slot `# TAI-02: mount the HITL decision router here`.
3. Tests: liveness on both prefixes; readiness returns 503 + reasons when agent down (DB monkeypatched).
4. Dockerfile: `python:3.12-slim` + uv, `uv sync --frozen --no-dev`, uvicorn :8000, `HEALTHCHECK` on `/health`.

## Success Criteria
- [x] `uv run ruff check . && uv run ruff format --check .` clean
- [x] `uv run pytest` passes
- [x] `docker build backend` succeeds

## Risk Assessment
- Starlette TestClient deprecation warning (upstream) — harmless; revisit if it becomes an error.
