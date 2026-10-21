# acb-delta
Document Evaluation for Legal Transformation Analysis - AI Hackathon - Bank summit

When a new legal document (VBPL) is issued, AI finds the internal bank documents it affects, suggests edits, and a human reviews them. Tasks and owners: [`PLAN.md`](PLAN.md).

## Quick start

Needs Docker (Compose v2).

```sh
./scripts/run.sh up           # first run creates .env with generated passwords, then starts everything
```

Same with plain Compose: `cp .env.example .env` (replace every `CHANGEME`), then `docker compose up -d --build --wait`.

| Service | URL |
|---|---|
| UI | http://localhost:3000 |
| API | http://localhost:8000/health · readiness: http://localhost:8000/api/health/ready |
| Agent (AgentBase contract) | http://localhost:8080/health · `POST /invoke` |
| MinIO console | http://127.0.0.1:9001 |

| `./scripts/run.sh …` | Does |
|---|---|
| `up` | Create `.env` if missing, build, start, wait until healthy, print URLs |
| `status` | Service health + readiness |
| `logs [service]` | Follow logs |
| `down` | Stop (keeps data) |
| `reset` | Stop and delete all data (asks first) |
| `test` | Lint + tests for backend, agent, frontend (no Docker needed) |

## Demo login

The UI opens on a branded login gate. This is a **demo-only** gate, not real authentication — the
credentials are hardcoded and checked in the browser (`frontend/src/hooks/use-auth.tsx`), so they
are meant to be shared with whoever runs the demo:

| Field | Value |
|---|---|
| Tài khoản | `acb` |
| Mật khẩu | `acb@2026` |

(The username is case-insensitive.) Any HTTPS basic-auth in front of a hosted demo is separate and
lives in that host's `.env` — never committed.

## Layout

| Path | What | Owner slots |
|---|---|---|
| `backend/` | FastAPI: health probes, regulation ingest + impact analysis (`/api/regulations`, `/api/jobs`, see [`docs/ria-ingest-analyze.md`](docs/ria-ingest-analyze.md)); HITL router goes here | TAI-02 |
| `agent/` | LangGraph graph on port 8080 (AgentBase Runtime contract), 4 stub nodes | TAI-01, MINH-01 (`retrieve`) |
| `frontend/` | Vite + React UI prototype, all HUY-01 screens | HUY-01 (live API wiring) |
| `db/init/` | Postgres init SQL (enables pgvector) | |
| `docs/` | Longer-lived notes; data contracts shared across tasks | |
| `research/` | Reference code RIA borrows ideas from (DICE, SLeDoC submodule); not built or tested, see [`research/README.md`](research/README.md) | MINH-01 |
| `scripts/run.sh` | Run / stop / test the stack | |
| `scripts/demo-data/` | Generates the demo PDFs and highlight positions | |

## UI prototype runs on demo data

The frontend ships with a mock API layer (`VITE_API_MODE=mock`, the default) so every screen is usable before the backend APIs exist. All VBPL, internal documents, impacts, decisions and evaluation numbers are **fictional** and the UI shows a "Dữ liệu demo" badge. Only the System status screen calls the real backend.

- Contracts the screens expect: [`frontend/src/api/types.ts`](frontend/src/api/types.ts) (proposed; TAI-02 / MINH-01 / KHOA-01 own the final shapes).
- Switch to real APIs: set `VITE_API_MODE=live` and rebuild. Endpoints not built yet show "Chưa có API (owner)".
- Demo data lives in [`frontend/src/api/mock/fixtures/`](frontend/src/api/mock/fixtures/). After editing the document or impact JSON, regenerate the PDFs and highlights:
  `uv run --with pymupdf python scripts/demo-data/generate_demo_pdfs.py`
