"""FastAPI entrypoint. Feature routers (documents, impacts, HITL decisions) mount under /api."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import ai, decisions, documents, evaluation, health, jobs, regulations, vbpls

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from app.db import get_engine
        from app.services.vector_store import init_db

        init_db(get_engine())
    except Exception:
        # DB may not be reachable immediately in some test environments
        pass
    # HITL tables + mock reviewers. Not swallowed: the decision API is useless without them.
    from app.hitl import init_tables

    init_tables()
    # KHOA-01: stored evaluation runs. Same reasoning as the HITL tables above, so not swallowed.
    from app.evaluation.store import init_tables as init_eval_tables

    init_eval_tables()
    # RIA tables and recovery of jobs cut off by a restart. A down DB must not stop the API
    # from starting: readiness reports it, and the RIA endpoints retry the schema on first use.
    try:
        from app.ria.jobs import recover_interrupted
        from app.ria.schema import ensure_schema

        ensure_schema()
        recover_interrupted()
    except Exception as exc:
        log.warning("RIA schema/job recovery skipped: %s", exc)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="acb-delta API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Bare /health for container healthchecks; /api/* for the frontend behind nginx.
    app.include_router(health.router)
    app.include_router(health.router, prefix="/api")

    # HUY-02: PDF upload and vector ingestion
    app.include_router(documents.router)
    app.include_router(documents.router, prefix="/api")

    # AI edit proposals
    app.include_router(ai.router)
    app.include_router(ai.router, prefix="/api")

    # TAI-02: VBPL intake, impacts, HITL decisions and audit trail.
    app.include_router(vbpls.router, prefix="/api")
    app.include_router(decisions.router, prefix="/api")

    # MINH-01: regulation ingest + impact analysis (RIA), and their async jobs
    app.include_router(regulations.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")

    # KHOA-01: evaluation runs for the dashboard
    app.include_router(evaluation.router, prefix="/api")
    return app


app = create_app()
