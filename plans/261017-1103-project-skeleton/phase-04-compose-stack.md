---
phase: 4
title: "Compose Stack"
status: completed
priority: P1
effort: "2h"
dependencies: [1, 2, 3]
---

# Phase 4: Compose Stack

<!-- Updated: Validation Session 1 - Langfuse moved to Cloud (no Langfuse/ClickHouse/Redis containers); MinIO switched to Chainguard images -->
<!-- Updated: Validation Session 2 - no Makefile; plain docker compose commands only -->

## Overview
One `docker-compose.yml` that runs the whole stack on this machine with healthchecks, plus `.env.example` and docs. **No Makefile** — every command is plain `docker compose` (owner preference). Ends Stage A (this delivery).

## Requirements
- Functional (documented in README + AGENTS.md):
  - Start: `docker compose up -d --build --wait` (builds, starts, waits until healthy)
  - Status: `docker compose ps` · Logs: `docker compose logs -f <service>`
  - Stop: `docker compose down` (keeps data) · Reset data: `docker compose down -v`
  - Tests/lint (no Docker needed): `cd backend && uv run pytest && uv run ruff check .` · same in `agent/` · `cd frontend && npm run lint && npm run build`
- Non-functional: every service has a healthcheck and `depends_on: condition: service_healthy`; named volumes; Postgres + MinIO bound to `127.0.0.1`; all secrets from `.env` (`.env` gitignored, `.env.example` committed with `CHANGEME` markers); fixed compose project name `acb-delta`.

## Architecture

| Service | Image | Host port |
|---|---|---|
| postgres | `pgvector/pgvector:pg16` | 127.0.0.1:5432 |
| minio | `cgr.dev/chainguard/minio` | 127.0.0.1:9000 (S3), 127.0.0.1:9001 (console) |
| minio-init (one-shot, creates bucket `documents`) | `cgr.dev/chainguard/minio-client` | – |
| agent | build `./agent` | 8080 |
| api | build `./backend` | 8000 |
| frontend | build `./frontend` | 3000 |

- `db/init/01-init.sql`: `CREATE EXTENSION IF NOT EXISTS vector;` in `acb_delta`.
- Langfuse: no containers. `.env.example` has `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST=https://cloud.langfuse.com` (empty keys = tracing off).
- LLM / embeddings: `.env.example` has `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `LLM_MODEL`, `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL` (empty; no container).

## Related Code Files
- Create: `docker-compose.yml`, `.env.example`, `.gitignore`, `db/init/01-init.sql`
- Modify: `README.md` (quick start), `AGENTS.md` (Commands section), `PLAN.md` (tick delivered TAI-06 items; Langfuse row in "Quyết định kỹ thuật" → Langfuse Cloud; remove langfuse/embedding from TAI-06 compose line or mark as env-only)

## Implementation Steps
1. Compose file + init SQL + `.env.example` + `.gitignore`.
2. `cp .env.example .env`, then `docker compose up -d --build --wait` → curl `:8000/health`, `:8080/health`, `:8000/api/health/ready`, `POST :8080/invoke` → open `:3000`.
3. `docker compose down` cleanly; confirm no leftover containers (`docker ps --filter label=com.docker.compose.project=acb-delta`).
4. Docs + PLAN.md updates.

## Success Criteria
- [x] `docker compose config` valid
- [x] `docker compose up -d --build --wait` exits 0 → `docker compose ps` all healthy
- [x] `/api/health/ready` returns all `ok`
- [x] `docker compose down` leaves no running containers from this project

## Risk Assessment
- Chainguard `:latest` tags move. Signal: image behaviour changes → pin digest.
- Port clash later on this machine. Signal: "address already in use" → identify owner with `lsof`, don't bump ports silently.
