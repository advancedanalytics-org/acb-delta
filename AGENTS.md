# AGENTS.md

Shared instructions for every coding agent (Claude Code, Codex, Cursor, Copilot, …) working in this repo. Read this file fully before making changes. `CLAUDE.md` imports it, so keep all shared rules here.

## Project

**acb-delta** — Document Evaluation for Legal Transformation Analysis (AI Hackathon, Bank Summit).

Goal: when a new legal document (VBPL) is issued, use AI to find which internal bank documents it affects, suggest edits, let a human review them (HITL), and evaluate/improve quality over time (evaluate + RLHF).

Glossary:

| Term | Meaning |
|---|---|
| VBPL | Văn bản pháp luật — external legal/regulatory documents |
| NHNN | Ngân hàng Nhà nước — State Bank of Vietnam (main VBPL source, usually PDF) |
| Văn bản nội bộ | The bank's internal documents (mocked for the hackathon) |
| HITL | Human-in-the-loop review of AI edit suggestions |
| RLHF | Learning from HITL feedback |

## Source of truth

- **`PLAN.md`** — task list, owners, dependencies, and agreed decisions. Always read it before starting work.
- **`README.md`** — project summary, quick start, repo layout.
- When you add or change a command, update **Commands** below in the same PR. Do not guess commands that are not in the repo.

## Commands

Stack: Python 3.12 + `uv` (`backend/`, `agent/`), Node 22 + npm (`frontend/`), Docker Compose for the whole stack. No Makefile.

### Run script (preferred)

`scripts/run.sh` is the entry point for running and checking the stack. Run it from any directory; it works with macOS bash 3.2.

| Command | What it does | Exit code |
|---|---|---|
| `./scripts/run.sh up` | Creates `.env` from `.env.example` if missing (random hex passwords, mode 600), checks ports, builds, starts, waits until every service is healthy, prints status + URLs | non-zero if Docker is missing/stopped, `.env` still has `CHANGEME`, a port is held by another program, or a service is unhealthy |
| `./scripts/run.sh status` | `docker compose ps` + `/api/health/ready` JSON | 0 even when degraded: read the JSON |
| `./scripts/run.sh logs [service]` | Follows logs (`-f`) | blocks until interrupted |
| `./scripts/run.sh down` | Stops containers, keeps data | |
| `./scripts/run.sh reset` | Deletes the Postgres + MinIO volumes after the user types `reset` | interactive |
| `./scripts/run.sh test` | ruff + pytest in `backend/` and `agent/`, `npm ci` + lint + build in `frontend/`; no Docker | non-zero on the first failure |

Rules for agents using it:

- Before `up`, run `status`. If the stack is already running, reuse it; `up` on a running stack is safe and rebuilds changed services.
- If `up` reports a busy port, find the owner from the printed `lsof` lines. Stop it only if you started it; otherwise ask your human. Never change ports to get around it.
- `logs` never returns on its own. Use `docker compose logs --tail 100 <service>` for a one-shot read.
- Never run `reset` (or `docker compose down -v`) unless your human asked: it deletes all local data. It needs typed input, so it cannot run unattended anyway.
- Run `down` when your task no longer needs the stack.
- Run `test` before opening a PR; CI does not cover these folders yet (see **CI**).
- Never print `.env` contents; it holds generated passwords.

### Plain commands

The script wraps these; they always work too.

| Task | Command |
|---|---|
| Configure | `cp .env.example .env`, then replace every `CHANGEME` (letters and digits only) |
| Start everything | `docker compose up -d --build --wait` |
| Status / logs | `docker compose ps` · `docker compose logs -f <service>` |
| Stop (keep data) / reset data | `docker compose down` · `docker compose down -v` |
| Backend test + lint | `cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check .` |
| Backend DB integration tests (RIA ingest/analyze) | start a throwaway `pgvector/pgvector:pg16`, then `cd backend && RIA_TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:<port>/<db> uv run pytest` (skipped when unset) |
| Seed internal documents into the RIA tables | `cd backend && DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/acb_delta uv run python -m app.ria.seed ../db/DOC-102.parsed.json` |
| Agent test + lint | `cd agent && uv run pytest && uv run ruff check . && uv run ruff format --check .` |
| Frontend lint + build | `cd frontend && npm ci && npm run lint && npm run build` |
| Frontend dev server | `cd frontend && npm run dev` (port 5173, proxies `/api` to `localhost:8000`) |
| Regenerate demo PDFs | `uv run --with pymupdf python scripts/demo-data/generate_demo_pdfs.py` |

Ports: UI 3000, API 8000, agent 8080 (fixed by AgentBase), Postgres 5432 and MinIO 9000/9001 on `127.0.0.1` only; override with the `*_PORT` values in `.env`.

### GCP demo VM

A demo copy of the whole stack runs on one GCP VM (project `acb-delta-demo-2340`, Singapore) behind Caddy (HTTPS + basic auth) at `https://34-143-129-52.sslip.io`. It is separate from the GreenNode target in `TAI-07`. Every push to `main` deploys there automatically (`.github/workflows/deploy-gcp.yml`); `scripts/gcp.sh` is the manual entry point and needs `gcloud` logged in to an account with access to that project.

| Command | What it does |
|---|---|
| `./scripts/gcp.sh deploy` | Fetches `origin/main` (or `GCP_REF`), uploads it, builds and starts the stack, prints URL + login. Keeps the VM's `.env` and data. Fails if the chat or embedding model, or the agent, does not answer one test call |
| `./scripts/gcp.sh status` · `logs [service]` · `ssh` | Health, last 100 log lines, shell on the VM |
| `./scripts/gcp.sh login` | Prints URL, user and password (from the VM's `.env`) |
| `./scripts/gcp.sh stop` · `start` | Stops / starts the VM to save credit; data and IP are kept |
| `./scripts/gcp.sh create` · `destroy` | Creates the VM (`e2-standard-4`, runs as service account `acb-delta-vm`), static IP and 80/443 firewall rule / deletes them with all data (asks first) |

Models on the VM come from `deploy/gcp/docker-compose.gcp.yml`, not from `.env`, and need no API key:

| Role | Service | Model |
|---|---|---|
| Chat (api + agent) | `litellm` → Vertex AI, location `global` | Qwen3-Next-80B Instruct (`deploy/gcp/litellm.yaml`), called as `qwen3-next-80b`. Authenticated as the VM's service account (`roles/aiplatform.user`, `cloud-platform` scope) |
| Embedding (api) | `embedding`: text-embeddings-inference on CPU | `BAAI/bge-m3`, 1024 dims; weights cached in the `embeddingdata` volume |

`scripts/gcp.sh deploy` writes `COMPOSE_FILE` into the VM's `.env`, so `docker compose` and `scripts/run.sh` on the VM always include that overlay. The CI deployer (`github-deployer`) needs `roles/iam.serviceAccountUser` on `acb-delta-vm` to SSH in.

Rules for agents: never print the login or `.env` in CI logs (the repo is public); never run `destroy` unless your human asked.

## Team and ownership

| Owner | Task IDs | Area |
|---|---|---|
| Tài | `TAI-01`…`TAI-06` | Edit suggestions, HITL, data (VBPL + mock internal docs), slides, demo, deploy |
| Khoa | `KHOA-01`, `KHOA-02` | Evaluate pipeline, RLHF |
| Huy | `HUY-01`, `HUY-02` | UI, NHNN pipeline (PDF → text → chunk → embedding) |
| Minh | `MINH-01`, `MINH-02` | Vector DB (embed + search + metadata), mock document format |

Rules:

- Work only on the task ID your human asked for. Do not edit another owner's code or task without that being the request.
- If your change needs something from another task, check **Phụ thuộc & điểm đồng bộ** in `PLAN.md`. If the dependency is not done or not agreed, stop and tell your human instead of inventing the interface.
- Shared contracts — mock document format, vector DB metadata schema, chunk/embedding strategy, evaluate and RLHF data flows — are decided in **Quyết định đã thống nhất** in `PLAN.md`. Never invent or silently change one. While a decision says `_chưa chốt_` (not decided), keep your code behind a small, clearly named adapter/config so it is cheap to change, and flag the assumption in your PR.

## Workflow

1. Read `PLAN.md`, find your task ID, confirm its dependencies are met.
2. Mark the task `[~]` in `PLAN.md` when starting.
3. Make the smallest change that completes the task. No unrelated refactors or formatting churn.
4. Verify it actually runs (test, script, or manual run) and report the result honestly, including failures.
5. Mark the task `[x]` (or `[!]` + reason if blocked) in `PLAN.md` in the same commit/PR as the work.
6. When a team decision is reached, record it under **Quyết định đã thống nhất** in `PLAN.md`.

Status markers: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked (write the reason next to it).

## Git conventions

- **Always pull before committing.** Run `git fetch origin` and `git pull --rebase origin main` (or rebase your branch on `origin/main`) before every commit and push, so you see teammates' changes first. If the rebase conflicts, resolve it (in `PLAN.md`, keep everyone's status updates) or stop and ask your human. Never force-push over someone else's work.
- **One branch per feature/task, merged only through a PR.** Never commit, push, or merge directly to `main`. Branch name: `<task-id-lowercase>-<short-slug>`, e.g. `huy-02-pdf-chunking`. Create it from an up-to-date `main`:
  ```sh
  git checkout main && git pull --rebase origin main
  git checkout -b huy-02-pdf-chunking
  ```
- Open the PR with `gh pr create --base main`. Merge only after CI passes and a teammate approves; do not merge your own PR without review.
- Conventional commits with the task ID as scope, per `PLAN.md`: `feat(HUY-02): chunking PDF NHNN`, `fix(MINH-01): metadata filter`. PR title uses the same format (CI checks it). `feat`/`fix` require a task ID; `docs`, `chore`, `ci`, etc. may omit it.
- One task per PR.
- Never commit secrets, API keys, `.env` files, or real bank/customer data. Internal documents in this repo must be mock data. Provide a `.env.example` for any new config.
- Large raw files (PDF corpora, embeddings, model weights) do not go in git; document where to get them instead.

## Code and docs

- Match the style of existing code in the area you touch. Prefer simple, readable code over abstractions.
- Implement real behavior. No fake results or hardcoded outputs to make a demo or check pass; mock data is fine only where `PLAN.md` says it is (internal documents).
- Plans and reports go in `plans/`; longer-lived docs go in `docs/`. Keep `PLAN.md` as the single task tracker — do not create parallel trackers.
- `PLAN.md` is written in Vietnamese; keep its wording and structure when editing it. Code, identifiers, and code comments are in English.

## CI

- `.github/workflows/ci.yml` runs on every PR to `main` and every push to `main`, on the org's self-hosted runner `aamacrunner` (macOS, ARM64).
- It checks the PR title format, then runs Python checks if `pyproject.toml`/`requirements.txt` exists and Node checks if `package.json` exists. When you add a stack, make sure its tests run there (`pytest`, or `npm test` / `npm run lint`).
- **Known gap:** those checks only look at the repo root, so `backend/`, `agent/` and `frontend/` are not built or tested in CI yet. CI changes are deferred until the `aamacrunner` Mac Mini is fixed (`plans/261017-1103-project-skeleton/phase-05-ci-cd-on-org-runner.md`). Until then, run the **Commands** checks locally before opening a PR.
- The runner is persistent and shared, not a fresh VM: never write outside the workspace, install global packages, or leave background processes running from CI steps.
- PRs from forks do not run on the self-hosted runner, for security.
- `.github/workflows/deploy-gcp.yml` deploys every push to `main` to the GCP demo VM on a GitHub-hosted runner. It authenticates keylessly (Workload Identity Federation limited to this repo's `main`) as `github-deployer@acb-delta-demo-2340.iam.gserviceaccount.com`, using the repo variables `GCP_PROJECT`, `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`. A failed build leaves the previous containers running.

## Agent-specific config

- `.claude/` holds Claude Code agents, hooks, rules, and skills. Other agents can ignore it; the rules that matter for everyone are in this file.
