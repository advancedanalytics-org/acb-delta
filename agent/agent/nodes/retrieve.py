from agent.state import ImpactState


def retrieve(state: ImpactState) -> ImpactState:
    """Find internal-document chunks related to each change (hybrid search on pgvector + rerank).

    Owner: MINH-01 (retrieve tool), wired by TAI-01. Expected output:
    {"candidates": [{"change", "chunk_id", "doc_id", "page", "bbox", "text"}, ...]}.
    """
    return {"candidates": []}
