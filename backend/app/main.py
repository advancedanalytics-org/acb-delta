"""FastAPI entrypoint. Feature routers (documents, impacts, HITL decisions) mount under /api."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import ai, decisions, documents, health, vbpls


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
    return app


app = create_app()
