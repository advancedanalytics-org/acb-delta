"""Liveness and readiness probes used by docker compose, CI, and the frontend status card."""

import httpx
from fastapi import APIRouter, Response, status

from app.config import get_settings
from app.db import ping_database

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up. Does not touch dependencies."""
    return {"status": "ok"}


@router.get("/health/ready")
def ready(response: Response) -> dict:
    """Readiness: report each dependency so failures are visible, not hidden."""
    checks: dict[str, str] = {}

    try:
        ping_database()
        checks["database"] = "ok"
    except Exception as exc:  # report any failure reason to the caller
        checks["database"] = f"error: {exc.__class__.__name__}: {exc}"

    try:
        httpx.get(f"{get_settings().agent_url}/health", timeout=2).raise_for_status()
        checks["agent"] = "ok"
    except Exception as exc:
        checks["agent"] = f"error: {exc.__class__.__name__}"

    ok = all(value == "ok" for value in checks.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ok else "degraded", "checks": checks}
