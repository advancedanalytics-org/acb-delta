"""Retrieval adapter. MINH-01 replaces the body of `retrieve_candidates`; callers stay the same.

Skeleton body: IDF-weighted keyword overlap over the paragraphs of a JSON corpus in the format of
`frontend/src/api/mock/fixtures/demo-documents.json` (documents → articles{heading, paragraphs}).
"""

import json
import logging
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from agent.config import get_settings
from agent.schemas import Candidate, Change

log = logging.getLogger(__name__)

_WORD = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


@lru_cache
def _load_corpus(path: str) -> tuple[list[Candidate], dict[str, float]]:
    """Flatten the corpus into one candidate per paragraph and compute token IDF."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    passages: list[Candidate] = []
    for doc in data.get("documents", []):
        for a, article in enumerate(doc.get("articles", []), start=1):
            for p, paragraph in enumerate(article.get("paragraphs", []), start=1):
                passages.append(
                    Candidate(
                        chunk_id=f"{doc['id']}:{a}:{p}",
                        doc_id=doc["id"],
                        location=article["heading"],
                        text=paragraph,
                    )
                )
    df = Counter(token for passage in passages for token in _tokens(passage.text))
    idf = {token: math.log(1 + len(passages) / count) for token, count in df.items()}
    return passages, idf


def retrieve_candidates(change: Change, k: int) -> list[Candidate]:
    """Return up to `k` passages most related to `change`, best first."""
    path = get_settings().corpus_path
    if not path:
        log.warning("CORPUS_PATH is empty; no internal documents to search")
        return []
    passages, idf = _load_corpus(path)
    query = _tokens(f"{change.clause} {change.text}")
    scored = [
        (sum(idf[t] for t in query & _tokens(passage.text)), i, passage)
        for i, passage in enumerate(passages)
    ]
    ranked = sorted((s for s in scored if s[0] > 0), key=lambda s: (-s[0], s[1]))
    return [passage for _, _, passage in ranked[:k]]
