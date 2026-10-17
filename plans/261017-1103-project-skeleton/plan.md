---
title: "Project Skeleton"
description: "Runnable monorepo skeleton + full clickable UI prototype, built and run on this machine; org-runner CI/CD and GreenNode deploy deferred"
status: in-progress
priority: P1
effort: "2-2.5d"
tags: [skeleton, infra, ui-prototype, TAI-06, TAI-07, HUY-01]
created: 2026-10-17
branch: chore-project-skeleton
---

# Project Skeleton

## Overview

A runnable monorepo skeleton every teammate can build their `PLAN.md` task inside. Each service starts, reports health, and has a marked empty slot for the owner's logic. Business logic is out of scope.

The frontend is a **full clickable prototype of every HUY-01 screen on demo data** (owner is team lead and wants to show the idea before teammates build). Data comes from a typed mock API layer that Huy later switches to live APIs.

**This delivery = Stage A only: build and run on this machine.** Later stages are documented so Stage A choices don't block them, but nothing is built for them now.

| Stage | Where it runs | Phases | State |
|---|---|---|---|
| **A – Local** | This machine (`docker compose`, ARM64, Docker 29.4) | 1–4 | **build now** |
| **B – Org runner** | `aamacrunner` Mac Mini: CI + team server | 5 | deferred by owner (Mac Mini SSL to `codeload.github.com` + Docker to fix first) |
| **C – GreenNode** | AgentBase + vServer + vDB + vStorage + MaaS | 6 | blocked: GreenNode account |

Stage B = `PLAN.md` "Phase 1 – Server team" (TAI-06 deploy). Stage C = "Phase 2 – GreenNode" (TAI-07).

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | `docker compose up -d --build --wait` on this machine starts the full stack, all healthy | P1 |
| 2 | Every service built to its Phase 2 contract (AgentBase :8080, env-only config) | P1 |
| 3 | Clear empty slots so teammates start their tasks without touching infra | P1 |
| 3b | Full clickable UI prototype (Inbox, Review workspace, Evaluation, Audit, System) on demo data, Vietnamese UI | P1 |
| 4 | Org-runner CI/CD and GreenNode deploy documented for later | P3 |

## Non-goals

Owned by teammates (skeleton only leaves marked slots): graph node logic (TAI-01), HITL tables/API (TAI-02), wiring UI to live APIs (HUY-01), PDF ingestion (HUY-02), chunk schema + retrieval (MINH-01), eval + feedback (KHOA-01/02). Also out: LLM/embedding containers and LiteLLM (models not chosen; env vars only), `seed`/`reindex` scripts (need MINH-01 schema), DB tables/migrations (no schema agreed), auth, **any CI/CD change** (existing `ci.yml` untouched), self-hosted Langfuse.

## Architecture

```text
browser ──► frontend :3000 (nginx) ──/api──► api :8000 (FastAPI) ──► postgres :5432 (pgvector, pg16)
                                                  │                 └► minio :9000 (S3, Chainguard image)
                                                  └──► agent :8080 (LangGraph, AgentBase contract)
                                                             ├──► LLM / embeddings via OPENAI_BASE_URL (external, unset in skeleton)
                                                             └──► Langfuse Cloud (traces, only when LANGFUSE_* set)
```

Phase 2 mapping: `postgres`→vDB, `minio`→vStorage, `agent`→AgentBase Runtime, `api`+`frontend`→vServer, LLM→MaaS, Langfuse Cloud unchanged. Switch by env vars only.

## Phases

| # | Phase | Stage | Status |
|---|-------|-------|--------|
| 1 | [Backend API](./phase-01-backend-api.md) | A | Done |
| 2 | [Agent Service](./phase-02-agent-service.md) | A | Done |
| 3 | [Frontend UI Prototype](./phase-03-frontend-ui-prototype.md) | A | Done |
| 4 | [Compose Stack](./phase-04-compose-stack.md) | A | Done |
| 5 | [CI/CD on Org Runner](./phase-05-ci-cd-on-org-runner.md) | B | Deferred |
| 6 | [GreenNode Deploy](./phase-06-greennode-deploy.md) | C | Blocked |

Dependencies: 1, 2, 3 independent → 4 needs 1–3 → 5 needs 4 → 6 needs 5.

## Success Criteria

- [x] `docker compose up -d --build --wait` on this machine → `postgres`, `minio`, `agent`, `api`, `frontend` healthy.
- [x] `curl :8000/health`, `curl :8080/health` → 200; `http://localhost:3000` shows status from `/api/health/ready` (DB, pgvector, agent all ok).
- [x] `POST :8080/invoke` runs the full 4-node graph with stub nodes and returns a result.
- [x] UI prototype: all 5 screens usable on demo data; Review decisions update highlights, progress, Inbox, Audit, with undo; light + dark; keyboard shortcuts (details in phase 3).
- [x] Tests + lint pass locally: `uv run pytest` / `uv run ruff check .` in `backend/` and `agent/`; `npm run lint` / `npm run build` in `frontend/`.
- [x] `docker compose down` leaves no running containers from this project.
- [x] `AGENTS.md` Commands section, `README.md` quick start, `PLAN.md` updated (TAI-06 ticks, Langfuse → Cloud, HUY-01 remaining scope = live wiring).

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Python | 3.12 + `uv` lockfiles | fast, reproducible; AgentBase SDK is Python |
| Postgres | `pgvector/pgvector:pg16` | safe match for vDB PostgreSQL (user confirmed) |
| Object storage | `cgr.dev/chainguard/minio` + `cgr.dev/chainguard/minio-client` | `minio/minio` no longer pullable from Docker Hub (verified); same S3 API |
| Langfuse | **Langfuse Cloud Hobby**, env vars only | user choice; free, no credit card; limits 2 users, 50k units/mo, 30-day data |
| LLM / embeddings | env vars only, no container | models not chosen (MINH-01 / TAI-06) |
| Frontend | full UI prototype: Vite + React 19 + TS + Tailwind v4 + shadcn/ui + TanStack Query/Table + React Router + Recharts | user (lead) wants the whole idea visible first |
| UI language | Vietnamese (code English) | users + judges Vietnamese |
| Prototype data | typed mock API layer, `VITE_API_MODE=mock\|live`, "Dữ liệu demo" badge; demo PDFs generated with real bbox | cheapest to swap/throw away; doesn't invent backend tables |
| Visual style | clean enterprise: slate + bank-blue accent, status tokens, light/dark, Be Vietnam Pro | user choice |
| API URL in frontend | relative `/api`, nginx proxy | no rebuild per environment |
| Ports | 3000 fe · 8000 api · 8080 agent · 5432/9000/9001 on 127.0.0.1 | all free on this machine; overridable in `.env` |
| CI/CD | none in this delivery | user: build and run locally first |
| Task runner | none — plain `docker compose` commands, no Makefile | user preference |

## Implementation Notes (Stage A, 2026-10-17)

Deviations found while building, all verified on this machine:
- `ghcr.io` pulls are denied on this network → Dockerfiles install `uv==0.8.23` from PyPI instead of copying from `ghcr.io/astral-sh/uv`.
- `react-pdf-highlighter-extended` requires React 18 → fallback from the risk table: `react-pdf` + own bbox overlay (`frontend/src/features/review/pdf-viewer.tsx`).
- TanStack Table v9 rewrote its API → pinned v8.
- MuPDF Story mis-paginates with CSS `line-height` → spacing via margins in the PDF generator.
- Chainguard MinIO image has no curl/grep → healthcheck uses bash `/dev/tcp`.
- CI not changed (owner decision) → backend/agent/frontend are not tested in CI yet; noted in AGENTS.md.
- Reports: `plans/reports/tester-261017-1130-project-skeleton.md`, `plans/reports/code-reviewer-261017-1130-project-skeleton.md`.

## Open Questions

None.

## Validation Log

### Session 1 — 2026-10-17

**Verification Results**
- Claims checked: 22 · Verified: 19 · Failed: 2 · Unverified: 1 · Tier: Full (6 phases)
- Verified: `backend/` files + `uv.lock` exist; `.github/workflows/ci.yml` exists; PLAN.md TAI-06 items match; ports 3000/3001/5432/8000/8080/9000/9001 free; Docker 29.4.2 arm64; images multi-arch (amd64+arm64): `pgvector/pgvector:pg16`, `clickhouse-server:25.12`, `redis:7`, `node:22-alpine`, `nginx:alpine`, `langfuse:3/4`, `cgr.dev/chainguard/minio`, `cgr.dev/chainguard/minio-client`.
- Failed: (1) `minio/minio`, `minio/mc` — Docker Hub "access denied" → Chainguard images. (2) Langfuse `:3` stale; official compose is v4 → moot, Langfuse moved to Cloud.
- Unverified: `python:3.12-slim`, `ghcr.io/astral-sh/uv:0.8` manifest check did not finish (standard images; confirmed at first `docker build`).
- Note: `actionlint` not installed locally — irrelevant now (CI deferred).

**Questions asked: 7** (incl. 3 at plan review)
| Topic | Decision |
|---|---|
| Frontend base scaffold | Yes, base only (superseded in Session 3: full UI prototype) |
| Postgres version | 16 |
| Image fixes | Chainguard MinIO; Langfuse v4 (moot) |
| Langfuse hosting | Langfuse Cloud Hobby |
| LLM / embedding server | Leave out, env vars only |
| CI runner | No CI/CD now — build and run on this machine first |

**Propagated:** plan.md (scope, architecture, decisions, success criteria), phase-02 (Langfuse Cloud tracing), phase-04 (no Langfuse profile, Chainguard MinIO, PLAN.md update), phase-05 (deferred, no work now), phase-06 (Langfuse stays Cloud).

### Whole-Plan Consistency Sweep
Searched all plan files for: `langfuse:3`, `up-all`, `clickhouse`, `redis`, `minio/minio`, `minio/mc`, `CREATE DATABASE langfuse`, `profile langfuse`, `self-host`, `actionlint`, `deploy-phase1`, `ci.yml`.
- Remaining hits are intentional: phase-05 (deferred CI/CD spec), Validation Log history, non-goal statements.
- Phase 1–4 contain no Langfuse containers, no Docker Hub MinIO, no CI/CD work.
- `ak plan validate` → valid.
- **Unresolved contradictions: 0.**

### Session 2 — 2026-10-17
- Owner: run with Docker, no `make`. Removed Makefile from phase-04 and plan.md; all run commands are `docker compose ...`; tests/lint documented as `uv`/`npm` commands per folder.
- Sweep: `grep -i make` across plan files → only this log entry. Contradictions: 0. Verification failures both resolved by user decisions → eligible for implementation.

### Session 3 — 2026-10-17
- Owner (team lead): build the full UI, not just the shell, to show the idea before teammates continue.
- Questions asked: 3 · UI language → Vietnamese · Prototype data → frontend mock layer (`VITE_API_MODE`) · Style → clean enterprise.
- Propagated: phase-03 rewritten and renamed `phase-03-frontend-ui-prototype.md`; plan.md overview, goals, non-goals (HUY-01 now = live wiring), phases table, success criteria, decisions, effort.
- Sweep: see below.
- Searched all plan files for `frontend-shell`, `Frontend Shell`, `base only`, `UI screens/design`, `Frontend base`: only the Session 1 log row remains, marked superseded. Phase 4 frontend service (`build ./frontend`, :3000) unchanged and compatible. `ak plan validate` → valid. **Unresolved contradictions: 0.**
