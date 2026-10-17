---
title: Project skeleton Stage A delivered
date: 2026-10-17
summary: "Backend, agent, full UI prototype and compose stack running on this machine; CI still blind to subfolders"
---

# Project skeleton Stage A delivered

## What happened
Built Stage A of plans/261017-1103-project-skeleton: FastAPI backend (health + readiness), LangGraph agent on the AgentBase contract (:8080, 4 stub nodes), full clickable Vietnamese UI prototype of all HUY-01 screens on a typed mock API layer, and a docker-compose stack (pgvector pg16, Chainguard MinIO, agent, api, frontend) that comes up healthy with one command.

## Surprises
- ghcr.io pulls denied on this network, even anonymously → uv installed from PyPI in Dockerfiles.
- react-pdf-highlighter-extended needs React 18 → react-pdf + own bbox overlay (plan's fallback).
- TanStack Table v9 rewrote its API → pinned v8.
- MuPDF Story breaks pagination when CSS line-height is set; PDFs were non-deterministic until metadata cleared and no_new_id used.
- react-diff-viewer-continued is code-oriented (fixed 1000px table, flex rows, line-break: anywhere) → overrides to wrap like prose.
- Radix Slot cannot merge NavLink's function className → active state computed manually.
- Chainguard MinIO has no curl/grep; health probe is pure bash /dev/tcp with an HTTP/1.1 Host header.

## Review outcome
Tester: all phase 1–4 checks green. Code review: fixed crypto.randomUUID on plain HTTP, double-decision on repeat keys, stale "all OK" health banner, CSV formula injection, nginx stale upstream + index.html caching, probe-only statement timeout, Langfuse lines in PLAN.md.

## Open
- CI does not test backend/agent/frontend (CI deferred by owner); documented in AGENTS.md.
- Huy must acknowledge HUY-01 scope change before merge.
- Demo document format is a prototype fixture, not a MINH-02 proposal.

## Next steps
Commit + PR (one task per PR rule may need a split), Phase 5 when the Mac Mini is fixed.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
