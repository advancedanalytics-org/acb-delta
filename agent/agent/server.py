"""HTTP entrypoint following the AgentBase Runtime contract: port 8080, GET /health."""

import logging
import uuid

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from agent.draft_graph import build_draft_graph, to_proposal
from agent.graph import build_graph
from agent.llm import LLMNotConfiguredError
from agent.schemas import AmendmentProposal, Change, DraftRequest, ImpactOut
from agent.tracing import get_callbacks

log = logging.getLogger(__name__)


# Longest VBPL text accepted (a long circular is ~150k characters); bounds the LLM cost of a call.
MAX_VBPL_TEXT_CHARS = 300_000


class InvokeRequest(BaseModel):
    vbpl_text: str = Field(min_length=1, max_length=MAX_VBPL_TEXT_CHARS)


class InvokeResponse(BaseModel):
    changes: list[Change]
    impacts: list[ImpactOut]


def create_app() -> FastAPI:
    app = FastAPI(title="acb-delta agent", version="0.1.0")
    graph = build_graph()
    draft_graph = build_draft_graph()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/invoke")
    def invoke(
        body: InvokeRequest,
        user_id: str | None = Header(None, alias="X-GreenNode-AgentBase-User-Id"),
        session_id: str | None = Header(None, alias="X-GreenNode-AgentBase-Session-Id"),
    ) -> InvokeResponse:
        try:
            result = graph.invoke(
                {"vbpl_text": body.vbpl_text}, config=_run_config(user_id, session_id)
            )
        except LLMNotConfiguredError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        return InvokeResponse(changes=result.get("changes", []), impacts=result.get("impacts", []))

    @app.post("/draft")
    def draft(
        body: DraftRequest,
        user_id: str | None = Header(None, alias="X-GreenNode-AgentBase-User-Id"),
        session_id: str | None = Header(None, alias="X-GreenNode-AgentBase-Session-Id"),
    ) -> AmendmentProposal:
        """Draft one minimal patch for one RIA finding. A patch that fails checks is `failed`."""
        try:
            result = draft_graph.invoke(
                {"request": body.model_dump()}, config=_run_config(user_id, session_id)
            )
        except LLMNotConfiguredError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        return to_proposal(body, result)

    return app


def _run_config(user_id: str | None, session_id: str | None) -> dict:
    if not session_id:
        # AgentBase always sends these; locally they are optional since memory is unused.
        # The graphs keep no state between runs, so the id only labels traces.
        log.info("No AgentBase session header; using a one-off thread id")
        session_id = f"local-{uuid.uuid4()}"
    return {
        "configurable": {"thread_id": session_id, "user_id": user_id},
        "callbacks": get_callbacks(),
    }


app = create_app()
