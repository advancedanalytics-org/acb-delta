"""Runs the agent for one VBPL and stores its impacts. Called as a FastAPI background task."""

import logging
import threading
import time

import httpx

from app.config import get_settings
from app.db import get_sessionmaker
from app.models.hitl import Impact, Vbpl

log = logging.getLogger(__name__)

# The agent makes several LLM calls per change; a long VBPL can take minutes.
INVOKE_TIMEOUT_SECONDS = 600
# One /draft is two or three LLM calls.
DRAFT_TIMEOUT_SECONDS = 180
# Agent runs for submitted VBPLs that may call the agent at once; later ones wait their turn,
# so a burst of submissions cannot fan out into unbounded parallel LLM spend.
MAX_PARALLEL_INVOKES = 2
_invoke_slots = threading.BoundedSemaphore(MAX_PARALLEL_INVOKES)


# Refresh the IAM token this long before it expires, so a slow call never starts with a stale one.
TOKEN_EXPIRY_MARGIN_SECONDS = 60
# Lifetime assumed when the IAM reply has no `expires_in`.
DEFAULT_TOKEN_LIFETIME_SECONDS = 300


class AgentBaseAuth(httpx.Auth):
    """Bearer token for an AgentBase Runtime whose inbound auth is "IAM Permissions".

    The token comes from GreenNode IAM (client credentials of a Service Account), is cached and
    shared across threads, and is fetched again once if the Runtime answers 401.
    """

    def __init__(self, client_id: str, client_secret: str, token_url: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self._token = ""
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def auth_flow(self, request: httpx.Request):
        request.headers["Authorization"] = f"Bearer {self.token()}"
        response = yield request
        if response.status_code == 401:
            request.headers["Authorization"] = f"Bearer {self.token(refresh=True)}"
            yield request

    def token(self, refresh: bool = False) -> str:
        with self._lock:
            if refresh or not self._token or time.monotonic() >= self._expires_at:
                self._token, lifetime = self._fetch()
                self._expires_at = time.monotonic() + lifetime - TOKEN_EXPIRY_MARGIN_SECONDS
            return self._token

    def _fetch(self) -> tuple[str, float]:
        response = httpx.post(
            self.token_url,
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        return body["access_token"], float(body.get("expires_in") or DEFAULT_TOKEN_LIFETIME_SECONDS)


_auth: AgentBaseAuth | None = None
_auth_lock = threading.Lock()


def agent_auth() -> AgentBaseAuth | None:
    """IAM auth when AGENTBASE_CLIENT_ID/SECRET are set (agent on AgentBase), else None."""
    global _auth
    settings = get_settings()
    if not (settings.agentbase_client_id and settings.agentbase_client_secret):
        return None
    with _auth_lock:
        if _auth is None or _auth.client_id != settings.agentbase_client_id:
            _auth = AgentBaseAuth(
                settings.agentbase_client_id,
                settings.agentbase_client_secret,
                settings.agentbase_token_url,
            )
        return _auth


def http_client() -> httpx.Client:
    """Separate function so tests can swap in an `httpx.MockTransport`."""
    return httpx.Client(
        base_url=get_settings().agent_url, timeout=INVOKE_TIMEOUT_SECONDS, auth=agent_auth()
    )


def draft(payload: dict, session_id: str) -> dict:
    """Agent POST /draft for one RIA finding → AmendmentProposal dict. Raises on HTTP errors."""
    with http_client() as client:
        response = client.post(
            "/draft",
            json=payload,
            headers={"X-GreenNode-AgentBase-Session-Id": session_id},
            timeout=DRAFT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()


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
        with _invoke_slots, http_client() as client:
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
            vbpl.error = describe(exc)
            session.commit()


def describe(exc: Exception) -> str:
    """Short reason shown in the API. Agent replies are ours; other errors may hold SQL or
    parameters, so only their type goes out (the full trace is in the log)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Agent HTTP {exc.response.status_code}: {exc.response.text[:500]}"
    if isinstance(exc, httpx.TransportError):
        return f"Agent unreachable: {exc.__class__.__name__}"
    return f"Internal error: {exc.__class__.__name__} (see API logs)"
