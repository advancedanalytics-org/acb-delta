---
phase: 2
title: "Agent Service"
status: completed
priority: P1
effort: "3h"
dependencies: []
---

# Phase 2: Agent Service

## Overview
LangGraph agent served over HTTP following the AgentBase Runtime contract, with the 4 pipeline nodes from `PLAN.md` TAI-01 as typed stubs so TAI-01 / MINH-01 only fill node bodies.

## Requirements
- Functional:
  - `GET /health` → 200 (AgentBase health check).
  - `POST /invoke` body `{ "vbpl_text": str }` → runs graph → `{ "changes": [], "impacts": [] }` with stubs.
  - Reads `X-GreenNode-AgentBase-User-Id` / `-Session-Id`; passes session id as LangGraph `thread_id`. Missing headers allowed locally (logged), since memory is not used yet.
  - Langfuse callback (Langfuse Cloud, `LANGFUSE_HOST=https://cloud.langfuse.com`) attached only when `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` set; otherwise tracing off, no errors. <!-- Updated: Validation Session 1 - Langfuse Cloud -->
  - Session id → LangGraph `thread_id` via in-memory checkpointer (no persistence in skeleton).
- Non-functional: port `8080` fixed (AgentBase: not configurable), bind `0.0.0.0`; LLM config env-only (`OPENAI_BASE_URL`, `OPENAI_API_KEY`, `LLM_MODEL`), unused by stubs; no `greennode-agentbase` dependency yet (Phase 6 adds wrapper).

## Architecture
```text
START → extract_changes → retrieve → judge_impact → draft_amendment → END
```
- `agent/state.py`: `ImpactState` TypedDict — `vbpl_text`, `changes`, `candidates`, `impacts`, `amendments`.
- `agent/nodes/<name>.py`: one function per node, returns `{}` partial state; docstring states owner + expected output (`# TAI-01`, retrieve `# MINH-01`).
- Linear edges now. TAI-01 swaps to `Send` fan-out per change and adds `interrupt()` for HITL (TAI-02) — noted in `graph.py`.
- `agent/graph.py`: `build_graph()` → compiled graph with in-memory checkpointer.
- `agent/server.py`: FastAPI app; `agent/tracing.py`: optional Langfuse handler.

## Related Code Files
- Create: `agent/pyproject.toml`, `agent/uv.lock`, `agent/agent/{__init__,config,state,graph,server,tracing}.py`, `agent/agent/nodes/{__init__,extract_changes,retrieve,judge_impact,draft_amendment}.py`, `agent/tests/{test_graph,test_server}.py`, `agent/Dockerfile`, `agent/.dockerignore`

## Implementation Steps
1. `pyproject.toml`: fastapi, uvicorn[standard], langgraph, langchain-openai, langfuse, pydantic-settings; dev pytest, ruff.
2. State + 4 stub nodes + graph builder.
3. Server: `/health`, `/invoke` (headers → config), optional tracing.
4. Tests: graph compiles and runs on sample input; `/health` 200; `/invoke` returns schema; session header becomes `thread_id`.
5. Dockerfile same pattern as backend, `EXPOSE 8080`, healthcheck.

## Success Criteria
- [x] ruff clean, pytest passes
- [x] `docker run -p 8080:8080` → `/health` 200, `/invoke` returns result

## Risk Assessment
- AgentBase request schema undocumented beyond `/health` + port; `/invoke` follows their FastAPI example. Signal: Phase 6 deploy fails health/invoke → adjust route in `server.py` only.
- AgentBase CPU arch undocumented; local image is ARM64 → Phase 6 builds `linux/amd64`.
