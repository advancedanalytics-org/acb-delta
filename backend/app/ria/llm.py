"""Optional LLM through an OpenAI-compatible /chat/completions endpoint, with a DB answer cache.

Disabled when OPENAI_BASE_URL or LLM_MODEL is empty; comparison then stays rule-based.
"""

import hashlib
import json
import logging

from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.ria.http_retry import post_json

log = logging.getLogger(__name__)


def llm_model() -> str | None:
    settings = get_settings()
    if not (settings.openai_base_url and settings.llm_model):
        return None
    return settings.llm_model


def chat_json(system: str, user: str, timeout: float = 120) -> dict:
    """Ask for a single JSON object. Raises on transport errors or non-JSON output."""
    settings = get_settings()
    body = {
        "model": settings.llm_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if settings.llm_extra_body:
        body.update(json.loads(settings.llm_extra_body))
    data = post_json(
        f"{settings.openai_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.openai_api_key or 'EMPTY'}"},
        json=body,
        timeout=timeout,
    )
    content = data["choices"][0]["message"]["content"]
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM did not return a JSON object")
    return json.loads(content[start : end + 1])


def prompt_version(system: str) -> str:
    return hashlib.sha256(system.encode()).hexdigest()[:12]


def cache_key(kind: str, system: str, user: str) -> str:
    settings = get_settings()
    material = json.dumps(
        [kind, settings.llm_model, settings.llm_extra_body, system, user], ensure_ascii=False
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _cache_get(key: str) -> dict | None:
    with get_engine().begin() as conn:
        return conn.execute(
            text(
                "UPDATE llm_cache SET hits = hits + 1, last_hit_at = now() "
                "WHERE cache_key = :k RETURNING response"
            ),
            {"k": key},
        ).scalar()


def _cache_put(key: str, kind: str, system: str, response: dict) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO llm_cache (cache_key, kind, model, prompt_version, response) "
                "VALUES (:k, :kind, :model, :pv, CAST(:r AS jsonb)) "
                "ON CONFLICT (cache_key) DO UPDATE SET response = EXCLUDED.response, "
                "created_at = now(), hits = 0"
            ),
            {
                "k": key,
                "kind": kind,
                "model": get_settings().llm_model,
                "pv": prompt_version(system),
                "r": json.dumps(response, ensure_ascii=False),
            },
        )


def chat_json_cached(kind: str, system: str, user: str, refresh: bool = False) -> tuple[dict, bool]:
    """chat_json with a DB cache. Returns (answer, from_cache).

    refresh=True skips the lookup and overwrites the entry (used to retry an answer that failed
    grounding). A cache error never fails the call: it falls back to asking the LLM.
    """
    enabled = get_settings().llm_cache_enabled
    key = cache_key(kind, system, user)
    if enabled and not refresh:
        try:
            cached = _cache_get(key)
        except Exception as exc:
            log.warning("llm cache read failed: %s", exc)
            cached = None
        if cached is not None:
            return cached, True
    answer = chat_json(system, user)
    if enabled:
        try:
            _cache_put(key, kind, system, answer)
        except Exception as exc:
            log.warning("llm cache write failed: %s", exc)
    return answer, False
