"""VBPL intake and the impacts the agent found for each one."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app import agent_client, hitl, review_bridge
from app.db import SessionDep
from app.models import hitl as models
from app.models import hitl_schemas as schemas

router = APIRouter(tags=["vbpls"])


@router.post("/vbpls", status_code=status.HTTP_202_ACCEPTED)
def create_vbpl(
    body: schemas.VbplCreate,
    background: BackgroundTasks,
    session: SessionDep,
) -> schemas.VbplOut:
    """Store the VBPL as processing and run the agent after the response is sent."""
    vbpl = models.Vbpl(**body.model_dump(), status="processing")
    session.add(vbpl)
    session.commit()
    background.add_task(agent_client.run_analysis, vbpl.id)
    return hitl.vbpl_rows(session, vbpl.id)[0]


@router.get("/vbpls")
def list_vbpls(session: SessionDep) -> list[schemas.VbplOut]:
    return hitl.vbpl_rows(session)


@router.get("/vbpls/{vbpl_id}")
def get_vbpl(vbpl_id: str, session: SessionDep) -> schemas.VbplOut:
    rows = hitl.vbpl_rows(session, vbpl_id)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VBPL not found")
    return rows[0]


@router.get("/vbpls/{vbpl_id}/impacts")
def list_impacts(vbpl_id: str, session: SessionDep) -> list[schemas.ImpactOut]:
    if session.get(models.Vbpl, vbpl_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VBPL not found")
    return hitl.impact_rows(session, vbpl_id)


@router.get("/impacts/{impact_id}/vbpl-clauses")
def list_impact_vbpl_clauses(impact_id: str, session: SessionDep) -> list[schemas.VbplClauseGroup]:
    """The cited VBPL clauses behind an impact, grouped by article (Điều) with their real titles.

    Keyed by `impact_id` alone (a uuid) so it does not depend on which VBPL id the UI routed with.
    Reads the obligations recorded on the impact and resolves their source clauses live from the
    RIA tables; returns [] for impacts with no RIA findings (e.g. the agent /invoke path).
    """
    impact = session.get(models.Impact, impact_id)
    if impact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Impact not found")
    model_output = impact.model_output or {}
    findings = [model_output.get("finding"), *(model_output.get("related_findings") or [])]
    obligation_ids = [
        f["obligation_id"] for f in findings if isinstance(f, dict) and f.get("obligation_id")
    ]
    return review_bridge.cited_vbpl_clauses(obligation_ids)
