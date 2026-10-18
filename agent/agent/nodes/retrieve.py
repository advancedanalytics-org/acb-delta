from agent.config import get_settings
from agent.retriever import retrieve_candidates
from agent.schemas import Candidate, Change


def retrieve(change: Change) -> list[Candidate]:
    """Find internal-document passages related to one change.

    Search itself lives in `agent.retriever` (MINH-01 replaces it with pgvector hybrid search +
    rerank); this helper only applies the run settings.
    """
    return retrieve_candidates(change, k=get_settings().retrieve_k)
