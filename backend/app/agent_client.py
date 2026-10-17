"""Runs the agent for one VBPL and stores its impacts. Called as a FastAPI background task."""

import logging

import httpx

from app.config import get_settings
from app.db import get_sessionmaker
from app.models.hitl import Impact, Vbpl

log = logging.getLogger(__name__)

# The agent makes several LLM calls per change; a long VBPL can take minutes.
INVOKE_TIMEOUT_SECONDS = 600


def http_client() -> httpx.Client:
    """Separate function so tests can swap in an `httpx.MockTransport`."""
    return httpx.Client(base_url=get_settings().agent_url, timeout=INVOKE_TIMEOUT_SECONDS)


def run_analysis(vbpl_id: str) -> None:
    """Invoke the agent; store impacts as pending and mark the VBPL awaiting_review, or failed.

    No DB session stays open during the agent call (up to minutes), so slow runs cannot drain the
    connection pool: read the text, close, call the agent, then write in a new session.
    """
    with get_sessionmaker()() as session:
        vbpl = session.get(Vbpl, vbpl_id)
        if vbpl is None:
            log.warning("VBPL %s disappeared before analysis", vbpl_id)
            return
        vbpl_text = vbpl.text
    try:
        with http_client() as client:
            response = client.post(
                "/invoke",
                json={"vbpl_text": vbpl_text},
                # Labels the agent's traces; one AgentBase session per VBPL.
                headers={"X-GreenNode-AgentBase-Session-Id": f"vbpl-{vbpl_id}"},
            )
            response.raise_for_status()
        with get_sessionmaker()() as session:
            for position, item in enumerate(response.json()["impacts"]):
                session.add(
                    Impact(
                        vbpl_id=vbpl_id,
                        position=position,
                        document_id=item["doc_id"],
                        chunk_id=item["chunk_id"],
                        location=item["location"],
                        change_clause=item["change_clause"],
                        citation=item["citation"],
                        affected_text=item["affected_text"],
                        page=item["page"],
                        bboxes=item["bboxes"],
                        type=item["type"],
                        severity=item["severity"],
                        reasoning=item["reasoning"],
                        suggested_text=item["suggested_text"],
                        model_output=item,
                    )
                )
            session.get(Vbpl, vbpl_id).status = "awaiting_review"
            session.commit()
    except Exception as exc:  # any failure must surface on the VBPL, not vanish in a log
        log.exception("Analysis failed for VBPL %s", vbpl_id)
        with get_sessionmaker()() as session:
            vbpl = session.get(Vbpl, vbpl_id)
            vbpl.status = "failed"
            vbpl.error = _describe(exc)
            session.commit()


def _describe(exc: Exception) -> str:
    """Short reason shown in the API. Agent replies are ours; other errors may hold SQL or
    parameters, so only their type goes out (the full trace is in the log)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Agent HTTP {exc.response.status_code}: {exc.response.text[:500]}"
    if isinstance(exc, httpx.TransportError):
        return f"Agent unreachable: {exc.__class__.__name__}"
    return f"Internal error: {exc.__class__.__name__} (see API logs)"
