"""HTTP entrypoint following the AgentBase Runtime contract: port 8080, GET /health."""

import logging
import uuid

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from agent.graph import build_graph
from agent.llm import LLMNotConfiguredError
from agent.schemas import Change, ImpactOut
from agent.tracing import get_callbacks

log = logging.getLogger(__name__)


class InvokeRequest(BaseModel):
    vbpl_text: str


class InvokeResponse(BaseModel):
    changes: list[Change]
    impacts: list[ImpactOut]


def create_app() -> FastAPI:
    app = FastAPI(title="acb-delta agent", version="0.1.0")
    graph = build_graph()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/invoke")
    def invoke(
        body: InvokeRequest,
        user_id: str | None = Header(None, alias="X-GreenNode-AgentBase-User-Id"),
        session_id: str | None = Header(None, alias="X-GreenNode-AgentBase-Session-Id"),
    ) -> InvokeResponse:
        if not session_id:
            # AgentBase always sends these; locally they are optional since memory is unused.
            # The graph keeps no state between runs, so the id only labels traces.
            log.info("No AgentBase session header; using a one-off thread id")
            session_id = f"local-{uuid.uuid4()}"
        config = {
            "configurable": {"thread_id": session_id, "user_id": user_id},
            "callbacks": get_callbacks(),
        }
        try:
            result = graph.invoke({"vbpl_text": body.vbpl_text}, config=config)
        except LLMNotConfiguredError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        return InvokeResponse(changes=result.get("changes", []), impacts=result.get("impacts", []))

    return app


app = create_app()
