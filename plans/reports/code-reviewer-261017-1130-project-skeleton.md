# Code Review: Project Skeleton (branch chore-project-skeleton, uncommitted)

## Scope
- Files: backend/ (7 py), agent/ (13 py), frontend/src (~55 files, ~5.2k LOC), docker-compose.yml, .env.example, .gitignore, db/init, scripts/demo-data, frontend nginx/Dockerfile, README.md / AGENTS.md / PLAN.md diffs
- Plan: plans/261017-1103-project-skeleton/plan.md + phase-01..04 (phases 5-6 out of scope)
- Checks run: backend + agent `ruff check`, `ruff format --check`, `pytest` (2 + 4 passed); frontend `tsc -b` clean, `npm run lint` exit 0 (8 warnings), `vite build` to scratch dir OK; `docker compose config --quiet` OK; live probes on the running stack (no up/down).

## Overall
The skeleton runs and is mostly sound. The optimistic-update math is correct for re-deciding and for undoing a re-decision. No secrets are tracked. ci.yml is untouched. Two problems block the stated goals. First, CI goes green while running none of the new tests. Second, every Review decision fails when the UI is opened over plain HTTP on a non-localhost address, which is how the team server demo will be reached.

## Critical
None.

## High

### H1. CI passes while running zero checks for the new code
`.github/workflows/ci.yml:54,60,71,79,85,93` uses `hashFiles('pyproject.toml', ...)` and `hashFiles('package.json')`, which match only files at the repo root. All manifests here are in `backend/`, `agent/`, `frontend/`, so the job runs "Nothing to build yet" and passes. On top of that, the workflow pins Python 3.11 and Node 20. The projects need `requires-python >=3.12`, and `cn` needs `engines.node >=22`, so the jobs would fail even if they were detected.
- Failure scenario: a teammate's PR breaks `backend` tests. CI goes green, and the PR is approved and merged.
- This conflicts with AGENTS.md "CI": "When you add a stack, make sure its tests run there." The plan defers CI on purpose ("any CI/CD change" is a non-goal, phase 5 deferred), so this is a user decision, not something to quietly undo. Options: (a) keep it deferred, but state in the PR description and the AGENTS.md CI section that CI does not test `backend/`, `agent/`, `frontend/` yet; (b) pull a minimal per-folder CI job forward from phase 5. Pick one before merge.

### H2. Review decisions throw on non-secure origins (`crypto.randomUUID`)
`frontend/src/api/mock/index.ts:77`. `crypto.randomUUID` only exists in secure contexts (HTTPS or localhost). Opening `http://<server-ip>:3000` (Stage B team server, or a teammate opening the lead's machine by IP) makes `decide()` throw `TypeError`. Every Chấp nhận/Sửa/Từ chối then shows "Không lưu được quyết định" and rolls back.
- Fix: use a fallback id, e.g. `` `dec-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}` ``, or `crypto.getRandomValues`, which works in insecure contexts.

## Medium

### M1. A double-click or held key decides several impacts
`impact-detail.tsx:35-42,155-168`, `use-review-shortcuts.ts:20-28`, `review-page.tsx:72-74`. `onDecide` advances the selection at once (`advanceFrom`), and `ImpactDetail` remounts with the next impact under the same button. The buttons are not disabled while `decide.isPending`, and the key listener ignores `event.repeat`.
- Scenario: a reviewer double-clicks "Chấp nhận", or holds `A` slightly too long. The next pending impact or impacts are accepted without being read, and each acceptance is written to the audit trail as that reviewer's decision.
- Fix: `if (event.repeat) return` in the shortcut hook; pass `decide.isPending` into `disabled`.

### M2. System screen keeps showing "all OK" after the backend goes down
`features/system/system-page.tsx:34`. The page shows the error only when `error && !data`. After one successful poll, `data` stays cached. When the API or agent dies later, nginx returns 502 HTML, `fetchHealth` throws, and `error` is set, but the page still shows the green "Tất cả dịch vụ hoạt động bình thường". This is the one screen that is meant to be "always real".
- Fix: show the error banner whenever `error` is set (keep the last-known checks shown as stale), or key the render on `isError`.

### M3. CSV export allows formula injection
`features/audit/audit-page.tsx:81`. `escape` only doubles quotes. Edited text, reasons and (in live mode) LLM or VBPL text that starts with `= + - @` or a tab/CR runs as a formula when the audit CSV is opened in Excel. That matters for a bank audit export.
- Fix: prefix such values with `'` before quoting.

### M4. Agent checkpointer grows without bound and carries state between runs
`agent/agent/graph.py:27`, `agent/agent/server.py:38-41`. `InMemorySaver` keeps every checkpoint (5 per invoke) for the life of the process. Each local request without a session header creates a new thread that is never freed, so the container's memory grows with traffic. Under AgentBase, repeat invokes on one session reuse thread state. Once TAI-01 adds a conditional path that skips a node, the response returns `impacts` or `amendments` left over from the previous VBPL.
- Nothing in the skeleton needs a checkpointer yet (no `interrupt()`). Either compile without it, or leave a comment that TAI-01/TAI-02 must reset state per run and add a persistent, bounded saver.

### M5. Passwords with URL-reserved characters break the stack
`docker-compose.yml:56` (`MC_HOST_local`) and `:77` (`DATABASE_URL`) put raw `MINIO_ROOT_PASSWORD` and `POSTGRES_PASSWORD` into URLs. The README says "replace every CHANGEME". A password from `openssl rand -base64` usually contains `/` or `+`, sometimes `@`, which makes `minio-init` fail or the API readiness report a confusing DB error.
- Fix: add "use URL-safe characters (A-Z a-z 0-9 - _)" to `.env.example`, or URL-encode the values.

### M6. nginx keeps the API's IP from startup and caches index.html heuristically
`frontend/nginx.conf:7-8`. `proxy_pass http://api:8000` looks up the name once, at startup. `docker compose up -d --build api` recreates `api` with a new IP while `frontend` keeps running, so every `/api` call returns 502 until `frontend` is restarted. Also, `index.html` has no `Cache-Control: no-cache`. After a redeploy, a cached `index.html` points at deleted hashed chunks, the lazy routes fail with "Failed to fetch dynamically imported module", and `router.tsx` has no `errorElement` for it.
- Fix: `resolver 127.0.0.11 valid=10s; set $api http://api:8000; proxy_pass $api;` (this keeps the `/api/...` path), and add `location = /index.html { add_header Cache-Control "no-cache"; }`.

### M7. PLAN.md: another owner's task ticked, and leftover contradictions
- `PLAN.md` HUY-01 diff: a non-owner ticks `[x] Khởi tạo Vite...` and adds an unmarked prose bullet that changes HUY-01's remaining scope. Phase-03's risk section requires "tell Huy before merge". AGENTS.md says not to edit another owner's task unless that is the request. Get Huy's acknowledgement and note it in the PR.
- `PLAN.md:29` ("vServer (FE + FastAPI + Langfuse)") and `:87` ("vServer: frontend + FastAPI + Langfuse") still put Langfuse on vServer. Row 25 now says "Langfuse Cloud (giữ nguyên)". Update both lines in Vietnamese.
- No `_chưa chốt_` item was changed (lines 164-169 untouched). Vietnamese wording and table structure are kept.

## Low
- Readiness leaks internals. `backend/app/routers/health.py:27` returns `str(exc)` from psycopg/SQLAlchemy, which includes host/IP, DB user and DB name. Anyone who can reach :3000 or :8000 sees it (both bound to 0.0.0.0). No password is exposed, and for a demo it's acceptable. Consider logging the full text and returning only the class name plus a short reason.
- Readiness can hang. `connect_timeout=3` bounds only the connect step. A DB that accepts the connection but stalls (locks, I/O) hangs the probe because there is no `statement_timeout`. Add `options=-c statement_timeout=3000` to `connect_args`.
- Undo from a stale toast flickers. Decide A on X, re-decide B on X, then click A's toast "Hoàn tác". `writeImpact(previous=pending)` briefly shows X as pending and the VBPL pending count as +1 (`queries.ts:164`, `review-page.tsx:87`), until the refetch shows B. It corrects itself, but it is confusing in a demo. Option: dismiss earlier toasts for the same impact when it is re-decided.
- Optimistic audit id `pending-${impactId}` (`queries.ts:119`) repeats if the same impact is re-decided before the refetch lands. That gives duplicate TanStack `getRowId` and React keys for a moment.
- The selection moves before the mutation (`review-page.tsx:74`). If the decision fails, the impact rolls back but the reviewer is already on another impact.
- Undo after leaving the page (unverified). The toast `onClick` calls `select()` from an unmounted ReviewPage and may navigate the user back to `/review/...?impact=`.
- CSV details (`audit-page.tsx:83,94-95`):
  - `URL.revokeObjectURL` runs synchronously right after `click()`, which can cancel the download in Safari. Defer it with `setTimeout`.
  - The time column is raw UTC ISO while the UI shows local time.
  - Accepted rows export an empty "Nội dung đã sửa", and `suggestedText` is not exported, so the CSV doesn't show what text was approved.
- The PDF viewer scrolls back to the selected highlight on every container resize (`pdf-viewer.tsx:58`, `pageWidth` in deps).
- Generator (`scripts/demo-data/generate_demo_pdfs.py`):
  - `read_text`/`write_text` don't set `encoding="utf-8"`, so it breaks on Windows.
  - Fonts are fetched from the unpinned `google/fonts` `main` branch.
  - `search_for` returns every occurrence on the page, so a repeated passage would be highlighted twice.
- The agent's `/invoke` (0.0.0.0:8080) and API :8000 have no auth. This matches the plan for Stage A. Revisit at Stage B, before LLM keys are set (cost abuse from the LAN).
- `backend/tests/test_health.py` covers only the "agent down" case. There is no test for all-ok (200) or DB failure.
- Do not `git add -A`: `.claude/` (20 MB, including agent memory) and `.agentkit/` are untracked and are not part of this task's scope.
- The header search box (`app-header.tsx:30`) is initialised once from `?q=`, so it goes stale when the Inbox search changes `q`.

## Explicit checks (b)
- Optimistic and undo logic (`queries.ts:86-104`, `mock/index.ts:20-38`): the pending delta comes from the cached previous status, so re-deciding accepted to rejected gives delta 0 (no double count). Undoing a re-decision restores the previous decision, both in the cache (`previous` carries the old decision) and in the store (latest-per-impact is derived again after `remove`). Snapshot and restore on error plus invalidate on settle are correct. No stale-closure bug found, apart from the Low items above.
- Shortcuts: blocked while typing, with modifiers, and while a dialog or menu is open. The review page has no Radix Select, so listbox typeahead is not an issue there. The one real defect is key auto-repeat (M1).
- PDF overlay: scale = rendered width / `originalWidth`, bbox is top-left PDF points (PyMuPDF), and scrolling waits for the selected page to measure. Correct for the generated unrotated A4 PDFs. Rotated or cropped real PDFs (HUY-02) will need `page.rotate` / cropbox handling.
- Audit date filter: local calendar day via `sv-SE` compared with `<input type=date>` values. Correct.
- 503 body parsing: `fetchHealth` reads the JSON on 503 and throws on non-JSON 502. Correct. Display bug: M2.
- Readiness timeouts: DB connect 3s plus agent 2s. Docker healthchecks use `/health`, so a slow DB doesn't flap containers. No statement timeout (Low).

## Acceptance criteria (a)
| Phase | Status |
|---|---|
| 1 Backend | Met: ruff/format/pytest pass; `/health`, `/api/health`, `/api/health/ready` live-probed 200 with all ok; TAI-02 slot comment present; no tables. |
| 2 Agent | Met: graph has 4 stub nodes, `/health`, `/invoke`, session header becomes thread_id (tested), Langfuse env-only, no AgentBase SDK. See M4. |
| 3 Frontend | Mostly met: 5 routes; fallback to react-pdf recorded in PLAN.md; demo badge; live mode throws "Chưa có API (owner)"; lint exit 0; build OK. Bundle ~0.6 MB gz total (review chunk 198 KB gz), under the 1.5 MB budget. Not verified by me (browser checks): no console errors, exact highlight placement, full keyboard walkthrough, light/dark. H2 breaks "Review decisions work" on non-localhost origins. |
| 4 Compose | `docker compose config` valid; all 5 services listening; Postgres/MinIO on 127.0.0.1 (verified with lsof); fixed project name; no Langfuse containers; no Makefile. Not verified (tester owns the stack): `down` leaves no containers. |
| Docs | AGENTS.md Commands, README quick start and PLAN.md updates present. See M7. |

## Contracts and patterns (c, d)
- `.github/workflows/ci.yml` is untouched (`git diff HEAD -- .github` is empty).
- Plan decisions are followed: no Makefile; Langfuse Cloud env-only; ports 3000/8000/8080, with 5432/9000/9001 on 127.0.0.1; no DB tables (`db/init` only enables `vector`); Chainguard MinIO; pg16.
- `frontend/src/api/types.ts` is marked PROPOSED with owners. `demo-documents.json` (articles/paragraphs) is a mock internal-doc format, while MINH-02's "Document format tài liệu mock" is still `_chưa chốt_`. Say in the PR that it is a prototype fixture, not a MINH-02 proposal.

## Security (e)
- `.env` is gitignored (`git check-ignore` confirms) and not tracked. `.env.example` only has `CHANGEME` placeholders. `.dockerignore` files exclude `.env`.
- nginx serves only `dist/`. `/api/docs` returns 404 through nginx. FastAPI `/docs` is reachable directly on :8000 (0.0.0.0); fine for Stage A.
- See M3 (CSV), M5 (URL-unsafe passwords), Low (readiness leak, no auth).
- `cn@0.5.0` is the official shadcn package (repo shadcn-ui/cn). It is pre-1.0 and was published yesterday, so watch for breaking minor versions.

## Metrics
- Type coverage: `tsc -b` clean (strict TS). Python not type-checked (no mypy configured).
- Tests: backend 2, agent 4, frontend none (no test script; not required by the plan).
- Lint: ruff 0 issues; oxlint 0 errors, 8 warnings (fast-refresh / react-table compiler hints).

## Recommended actions
1. Decide H1 with the owner: document "CI does not test subprojects yet", or pull in a minimal CI job.
2. Fix H2 (randomUUID fallback). One line.
3. Fix M1 (ignore `event.repeat`; disable buttons while a decision is pending) and M2 (System page error state).
4. Fix M3 (CSV formula prefix), M6 (nginx resolver and index.html no-cache), M5 (doc or encode passwords).
5. M7: tell Huy, and fix PLAN.md lines 29/87.
6. M4: drop the checkpointer or document the reset-per-run requirement for TAI-01.

## Unresolved questions
- H1: is "CI green but tests nothing" acceptable until phase 5? (owner decision)
- Has Huy agreed to the HUY-01 scope change and the ticked sub-item?
- Will `.claude/` / `.agentkit/` be committed in this PR or kept local?
