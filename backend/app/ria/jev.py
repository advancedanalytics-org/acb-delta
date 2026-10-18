"""TypeSafe Jev structured decisions (design section 12) through the OpenRouter Decisions API.

POST {JEV_BASE_URL}/decisions {"model", "state", "questions"} → {"answers": {name: {...}}}.
A "noul" question returns P(its "true" criterion holds); a "choice" question returns a probability
per option. Used as the Engine 1 reranker (rerank.py). Disabled when JEV_BASE_URL or JEV_MODEL
is empty.
"""

from app.config import get_settings
from app.ria.http_retry import post_json

MAX_QUESTIONS_PER_CALL = 24


def jev_model() -> str | None:
    settings = get_settings()
    if not (settings.jev_base_url and settings.jev_model):
        return None
    return settings.jev_model


def decide(state, questions: dict[str, dict], timeout: float = 60) -> dict[str, dict]:
    """Answers keyed by question name. Splits large question sets across calls."""
    settings = get_settings()
    names = list(questions)
    answers: dict[str, dict] = {}
    for i in range(0, len(names), MAX_QUESTIONS_PER_CALL):
        chunk = {n: questions[n] for n in names[i : i + MAX_QUESTIONS_PER_CALL]}
        data = post_json(
            f"{settings.jev_base_url.rstrip('/')}/decisions",
            headers={"Authorization": f"Bearer {settings.jev_api_key or 'EMPTY'}"},
            json={"model": settings.jev_model, "state": state, "questions": chunk},
            timeout=timeout,
        )
        answers.update(data.get("answers") or {})
    return answers


def noul(question: str, true: str, false: str) -> dict:
    return {"type": "noul", "instructions": question, "criteria": {"true": true, "false": false}}


def probability(answer: dict | None) -> float | None:
    """P(true) of a noul answer, None when missing or malformed."""
    if not answer or answer.get("type") != "noul":
        return None
    try:
        return max(0.0, min(1.0, float(answer["noul"])))
    except (KeyError, TypeError, ValueError):
        return None


def choice_probability(answer: dict | None, label: str) -> float:
    """P(label) of a choice answer; 0 when missing or malformed."""
    if not answer or answer.get("type") != "choice":
        return 0.0
    probabilities = answer.get("probabilities") or {}
    try:
        if label in probabilities:
            return max(0.0, min(1.0, float(probabilities[label])))
        if answer.get("choice") == label:
            return max(0.0, min(1.0, float(answer.get("confidence", 1.0))))
    except (TypeError, ValueError):
        pass
    return 0.0
