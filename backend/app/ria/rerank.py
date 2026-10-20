"""Optional reranker for Engine 1 (design section 05.6). Two backends:

- RERANK_BACKEND=jev: TypeSafe Jev decisions (JEV_* settings). One call asks, for every candidate,
  a "choice" question (same activity / same domain only / unrelated); the score is
  P(same activity).
- RERANK_BACKEND=rerank: a Cohere/Jina-style cross-encoder, POST {RERANK_BASE_URL}/rerank
  {"model", "query", "documents", "top_n"} → {"results": [{"index", "relevance_score"}]}.

Scores of the two backends live on different scales, so each has its own default threshold.
"""

from app.config import get_settings
from app.ria import jev
from app.ria.http_retry import post_json

# Calibrated on the NHNN corpus vs DOC-102 (docs/ria-ingest-analyze.md, "Cấu hình model").
DEFAULT_MIN_SCORE = {"jev": 0.5, "rerank": 0.2}

# A three-way choice separates "same activity" from "same domain" far better than a yes/no
# question: on labelled pairs every relevant clause scored >= 0.75 and every unrelated one
# <= 0.74 (the yes/no form put KYC clauses at 0.93 for data-protection duties).
_JEV_QUESTION = "Quan hệ giữa điều khoản nội bộ {cid} và nghĩa vụ pháp lý là gì?"
_JEV_CHOICES = {
    "same_activity": (
        "Quy định chính hành động và đối tượng mà nghĩa vụ điều chỉnh; "
        "nghĩa vụ đổi thì điều khoản này phải rà soát hoặc sửa."
    ),
    "same_domain_only": (
        "Cùng lĩnh vực chung (khách hàng, hồ sơ, dữ liệu) nhưng khác hành động hoặc khác đối tượng."
    ),
    "unrelated": "Không liên quan, hoặc chỉ là danh sách đơn vị, định nghĩa, phạm vi áp dụng.",
}


def backend() -> str | None:
    settings = get_settings()
    if settings.rerank_backend == "jev":
        return "jev" if jev.jev_model() else None
    if settings.rerank_base_url and settings.rerank_model:
        return "rerank"
    return None


def rerank_model() -> str | None:
    kind = backend()
    if kind == "jev":
        return jev.jev_model()
    return get_settings().rerank_model if kind else None


def default_min_score() -> float:
    return DEFAULT_MIN_SCORE.get(backend() or "rerank", 0.2)


def rerank(query: str, documents: list[str], timeout: float = 60) -> list[float]:
    """Relevance score of each document for the query, in input order."""
    if not documents:
        return []
    if backend() == "jev":
        return _rerank_jev(query, documents, timeout)
    settings = get_settings()
    data = post_json(
        f"{settings.rerank_base_url.rstrip('/')}/rerank",
        headers={"Authorization": f"Bearer {settings.rerank_api_key or 'EMPTY'}"},
        json={
            "model": settings.rerank_model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
        },
        timeout=timeout,
    )
    scores = [0.0] * len(documents)
    for item in data["results"]:
        scores[item["index"]] = float(item["relevance_score"])
    return scores


def _rerank_jev(query: str, documents: list[str], timeout: float) -> list[float]:
    ids = [f"c{i}" for i in range(len(documents))]
    answers = jev.decide(
        {"nghia_vu": query, "dieu_khoan_noi_bo": dict(zip(ids, documents, strict=True))},
        {
            cid: {
                "type": "choice",
                "instructions": _JEV_QUESTION.format(cid=cid),
                "criteria": _JEV_CHOICES,
            }
            for cid in ids
        },
        timeout=timeout,
    )
    return [jev.choice_probability(answers.get(cid), "same_activity") for cid in ids]
