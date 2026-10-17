---
phase: 6
title: "GreenNode Deploy"
status: pending
priority: P3
effort: "1d (when account ready)"
dependencies: [5]
---

# Phase 6: GreenNode Deploy

> Blocked on GreenNode account. Documented now so earlier phases don't block it; nothing built in this PR. Matches `PLAN.md` TAI-07.

## Overview
Move the same images to GreenNode by swapping env vars and deploy targets.

## Requirements
- Functional: agent on AgentBase Runtime; `api` + `frontend` on a vServer; data on vDB PostgreSQL + vStorage; LLM/embeddings via MaaS; Langfuse stays on Langfuse Cloud (same env vars). <!-- Updated: Validation Session 1 - Langfuse Cloud -->
- Prerequisite: Stage B (phase 5) is not strictly required; GreenNode deploy can go direct from Stage A if the Mac Mini is still not fixed.
- Non-functional: no app code changes except adding the `greennode-agentbase` wrapper in `agent/server.py`.

## Implementation Steps
1. IAM service account with AgentBase permissions.
2. Check MaaS catalog for the chosen LLM + embedding model (MINH-01 decision).
3. Agent: add `greennode-agentbase` wrapper; `docker buildx build --platform linux/amd64` (verify AgentBase arch) → GreenNode Container Registry → Agent Runtime; confirm `/health`.
4. vDB PostgreSQL 16, enable pgvector; `pg_dump` local → `pg_restore`.
5. MinIO → vStorage (`mc mirror`); set `S3_ENDPOINT`.
6. vServer: same compose with `postgres`, `minio`, `agent` disabled (override file); `DATABASE_URL` → vDB, `AGENT_URL` → AgentBase endpoint; Langfuse env unchanged.
7. Env → MaaS (`OPENAI_BASE_URL`, embeddings); re-embed if model changed; rerun KHOA-01 eval.
8. Add `deploy-phase2.yml`.

## Success Criteria
- [ ] Agent healthy on AgentBase
- [ ] Frontend on vServer shows all checks `ok` against vDB + AgentBase
- [ ] Eval metrics not worse than Stage B

## Risk Assessment
- AgentBase request/arch details undocumented → verify on first deploy, adjust `server.py` only.
- Embedding model missing on MaaS → re-embed + rerun retrieval eval (PLAN.md risk).
