"""VBPL intake and the impacts the agent found for each one."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app import agent_client, hitl
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
