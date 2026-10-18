"""Optional LLM judge through an OpenAI-compatible /chat/completions endpoint.

Disabled when OPENAI_BASE_URL or LLM_MODEL is empty; comparison then stays rule-based.
"""

import json

import httpx

from app.config import get_settings


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
    resp = httpx.post(
        f"{settings.openai_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.openai_api_key or 'EMPTY'}"},
        json=body,
        timeout=timeout,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM did not return a JSON object")
    return json.loads(content[start : end + 1])
