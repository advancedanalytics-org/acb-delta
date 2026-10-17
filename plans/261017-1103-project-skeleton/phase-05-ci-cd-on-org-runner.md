---
phase: 5
title: "CI/CD on Org Runner"
status: pending
priority: P3
effort: "2h (when Mac Mini fixed)"
dependencies: [4]
---

# Phase 5: CI/CD on Org Runner

<!-- Updated: Validation Session 1 - deferred by owner; no CI/CD work in this delivery -->

> **Deferred.** Owner decision 2026-10-17: build and run on this machine first; no CI/CD changes now. Existing `.github/workflows/ci.yml` stays untouched. Start this phase after the Mac Mini is fixed.

## Overview
Per-service CI jobs and a Phase 1 deploy workflow targeting the `aamacrunner` Mac Mini (team server).

## Requirements
- Functional:
  - `ci.yml`: `pr-title` (existing); `backend`, `agent` (setup-uv → `uv sync --frozen` → ruff → pytest); `frontend` (setup-node 22 → `npm ci` → lint → build); `compose` (`docker compose config` + `build`). Runner choice decided at start (GitHub-hosted is free for this public repo; `aamacrunner` once fixed).
  - `deploy-phase1.yml` (push main + manual, `aamacrunner`): rsync → `~/deployments/acb-delta`; `.env` from secret `PHASE1_ENV`; `docker compose -p acb-delta up -d --build --wait --remove-orphans`; on failure print logs.
- Non-functional: concurrency (CI cancels stale; deploy never cancels); `permissions: contents: read`; skip fork PRs on self-hosted.

## Related Code Files
- Modify: `.github/workflows/ci.yml`, `AGENTS.md` (CI section)
- Create: `.github/workflows/deploy-phase1.yml`

## Prerequisites (owner, on Mac Mini)
- Fix SSL to `codeload.github.com` (CI logs 2026-10-17: "The SSL connection could not be established" downloading `actions/checkout`, failed twice).
- Docker running and on the runner service `PATH`.
- Repo secret `PHASE1_ENV`.

## Success Criteria
- [ ] actionlint clean (via `rhysd/actionlint` image)
- [ ] All CI jobs green
- [ ] Deploy brings stack up on Mac Mini; team reaches `http://<mac-mini-ip>:3000`

## Risk Assessment
- Runner = server: CI must never run `compose up`; deploy uses separate dir + project name.
