"""FastAPI entrypoint. Feature routers (documents, impacts, HITL decisions) mount under /api."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import health


def create_app() -> FastAPI:
    app = FastAPI(title="acb-delta API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Bare /health for container healthchecks; /api/* for the frontend behind nginx.
    app.include_router(health.router)
    app.include_router(health.router, prefix="/api")
    # TAI-02: mount the HITL decision router here under prefix="/api".
    return app


app = create_app()
