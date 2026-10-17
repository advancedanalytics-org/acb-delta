# QA Report: Project Skeleton (Stage A)

Branch `chore-project-skeleton`, uncommitted. Source not modified. Scope: phases 1-4. Phases 5-6 out of scope.

## Results

| # | Check | Result |
|---|---|---|
| 1 | backend: ruff check, ruff format --check, pytest | PASS. `All checks passed!`, `7 files already formatted`, `2 passed, 1 warning` (Starlette TestClient httpx deprecation, upstream) |
| 2 | agent: same | PASS. `All checks passed!`, `13 files already formatted`, `4 passed` |
| 3a | frontend `npm run lint` (oxlint) | PASS, exit 0. 0 errors, 12 warnings: 8 non-shadcn (router.tsx x4, use-theme, use-current-user, main.tsx, audit-page.tsx `incompatible-library`), 4 in `components/ui/` (toggle, button, badge, tabs) |
| 3b | frontend `tsc -b` + `npm run build` | PASS, exit 0. Build warns: chunk `review-page` 653 kB raw / 198 kB gz, `index` 147 kB gz, `evaluation-page` 108 kB gz. Total well under 1.5 MB gz budget |
| 4a | `docker compose ps -a` | PASS. postgres, minio, api, agent, frontend `healthy`; minio-init `Exited (0)` |
| 4b | endpoints | PASS. `:8000/health` 200; `:8080/health` 200; `:8000/api/health/ready` 200 `{"status":"ok","checks":{"database":"ok","agent":"ok"}}`; `:3000/api/health/ready` 200; `POST :8080/invoke {"vbpl_text":"Điều 1."}` 200 `{"changes":[],"impacts":[]}` |
| 4c | SPA routes | PASS. `/`, `/review/vbpl-tt-31-2026`, `/audit` all 200 `text/html` |
| 4d | `/demo/doc-cv-01.pdf` | PASS. 200 `application/pdf` |
| 4e | PDF worker | PASS. `/assets/pdf.worker.min-Dswkl-cV.mjs` (referenced from lazy `review-page-B-gmF3x8.js`) 200 `application/javascript`, 1.27 MB, `max-age=31536000` immutable |
| 5 | Readiness failure path | PASS. After `docker compose stop agent`: `/api/health/ready` and `/health/ready` 503 `{"status":"degraded","checks":{"database":"ok","agent":"error: ConnectError"}}`. Liveness `/health` stayed 200. Restarted with `start` + `up -d --wait`, exit 0, `/api/health/ready` back to 200 |
| 6a | `docker compose config -q` | PASS, exit 0 |
| 6b | `.env` ignored | PASS. `.gitignore:2:.env` matches; `.env.example` re-included by `.gitignore:4` |
| 6c | Secret leak scan | PASS for passwords. `POSTGRES_PASSWORD` and `MINIO_ROOT_PASSWORD` (32 chars) found in no non-ignored file besides `.env`. `OPENAI_API_KEY`, `LANGFUSE_*` empty. Usernames `acb` appear in many files (`.env.example`, compose defaults, code); not secrets. Key-pattern scan (`sk-…`, PEM, `AKIA…`, `ghp_…`) hits only in `.claude/skills/*` docs and test fixtures (sample strings, not real keys) |
| 7 | Demo data integrity | PASS. 15 impacts, 15 highlight entries, all `bboxes` non-empty, all within page bounds, all `page` <= `pageCounts`. Every `affectedText` found verbatim in `demo-documents.json` (per-impact occurrence count 1). No orphan highlights. Per VBPL: `vbpl-tt-31-2026` 13, `vbpl-tt-27-2026` 2 |
| 8 | Browser flow (agent-browser, session `tester-acb`) | PASS (partial, see notes). `/review` redirects to `/review/vbpl-tt-31-2026`; 11 overlays (`section[aria-label="Văn bản nội bộ"] .absolute.cursor-pointer`) = 11 bboxes of doc-cv-01 (imp-01..06). Progress `3/13 đã duyệt` then `j` + `a` gives `4/13 đã duyệt`. `/audit` top row: `12:03 17/10/2026 Nguyễn Minh Anh Chuyên viên pháp chế · 31/2026/TT-NHNN · QĐ-CV-01 · Điều 3, khoản 1 · Chấp nhận`. Browser session closed |

## Test coverage and gaps

- Backend: 2 tests (liveness both prefixes; readiness 503 with DB monkeypatched). No test against a real Postgres/pgvector. Coverage not measured (no pytest-cov configured).
- Agent: 4 tests (graph run, /health, /invoke schema, session header to thread_id). Coverage not measured.
- Frontend: no test runner at all. Only lint + build. Review decisions, undo, shortcuts A/E/R/J/K/?, audit, and evaluation were not exercised. Only j/a and audit row verified in browser.
- Not verified: Undo (Hoàn tác), E/R shortcuts, `?` help, light/dark theme, Inbox/Evaluation/System screens, `VITE_API_MODE=live` path, Langfuse tracing off/on behavior.

## Performance

- Test runtime: backend 0.20 s, agent 0.21 s.
- Frontend build: about 0.4 s (vite), lint quick. Largest chunk 653 kB raw.
- Stack: all services healthy within about 2-5 min of `up`. Agent restart to healthy: under 10 s.

## Concerns

1. [!] Frontend has zero automated tests. Phase 3 success criteria (undo, shortcuts, light/dark) are unverified by any test.
2. [!] Untracked `.claude/` (whole kit, includes `settings.json`, skill docs, `.env.example` files) and `.agentkit/` would be swept in by a naive `git add -A`. Decide commit scope explicitly.
3. Build warns chunk > 500 kB (`review-page`). Not a failure. Consider `build.chunkSizeWarningLimit` or manual chunking if the team cares.
4. Oxlint: 8 non-shadcn `only-export-components`/`incompatible-library` warnings. Warnings only, not failures.
5. Browser state changed: one accept (`QĐ-CV-01 Điều 3 khoản 1`) now sits in the mock store of the `tester-acb` browser profile (localStorage). Source unchanged. Undo or clear localStorage if the demo must start clean. Progress began at `3/13` before I touched it, so prior decisions were already persisted in that profile.
6. Impact fixtures have no `status` field (all 15 undefined). Presumably the mock store seeds `pending`. Not verified by source read.
7. Unknown `/assets/*` returns nginx 404 `text/html` (153 B). Harmless.

## Re-verification after restart

- `docker compose ps`: all healthy, minio-init exited 0. Stack left running.
- `/api/health/ready` 200, `:3000/api/health/ready` 200.
- Backend pytest exit 0, agent pytest exit 0.
- `git status` unchanged except the new `plans/reports/` file. Built `frontend/dist` is gitignored.

## Unresolved questions

1. Should the frontend get a test runner (Vitest + RTL) before merge, or is manual walkthrough accepted for the prototype?
2. Commit scope: is `.claude/` and `.agentkit/` meant to be in this PR?
3. Should the mock demo state be reset before the lead's demo (localStorage clear)?

Status: DONE_WITH_CONCERNS
Summary: All phase 1-4 acceptance checks pass: lint/tests green in backend and agent, frontend lint (0 errors, 12 warnings) and build pass, stack healthy, readiness 503 path verified and restored, secrets not leaked, demo data consistent, and review j/a + audit flow works in browser. Gaps: no frontend tests, several Phase 3 criteria unverified, and untracked `.claude/` needs a scope decision.
Concerns/Blockers: frontend has no automated tests; untracked `.claude/` and `.agentkit/` may be committed unintentionally; one demo accept left in the tester browser's localStorage.
