"""Optional LLM judge through Gemini (langchain_google_genai) or OpenAI-compatible endpoint.

Disabled when LLM credentials/model are empty; comparison then stays rule-based.
"""

import json
import os

import httpx

from app.config import get_settings


def _gemini_api_key(settings) -> str | None:
    return (
        settings.gemini_api_key
        or settings.google_api_key
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or settings.openai_api_key
    )


def llm_model() -> str | None:
    settings = get_settings()
    llm_type = (settings.llm_type or "openai").strip().lower()
    if llm_type == "gemini":
        if not _gemini_api_key(settings):
            return None
        return settings.llm_model or "gemini-2.0-flash"
    if not (settings.openai_base_url and settings.llm_model):
        return None
    return settings.llm_model


def chat_json(system: str, user: str, timeout: float = 120) -> dict:
    """Ask for a single JSON object. Raises on transport errors or non-JSON output."""
    settings = get_settings()
    llm_type = (settings.llm_type or "openai").strip().lower()

    if llm_type == "gemini":
        api_key = _gemini_api_key(settings)
        if not api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY is not set")
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_google_genai import ChatGoogleGenerativeAI

        model_name = settings.llm_model or "gemini-2.0-flash"
        model = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=0,
            timeout=timeout,
        )
        res = model.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        content = res.content
        if isinstance(content, list):
            content = " ".join(str(p) for p in content)
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end < start:
            raise ValueError("LLM did not return a JSON object")
        return json.loads(content[start : end + 1])
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
