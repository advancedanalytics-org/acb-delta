import json
from pathlib import Path

from app.ria.retrieval import InternalCorpus, RetrievalParams, is_framing, select_candidates
from app.ria.seed import infer_level

DOC_102 = Path(__file__).resolve().parents[2] / "db" / "DOC-102.parsed.json"


def _doc_102_clauses() -> dict[str, dict]:
    """DOC-102 as load_internal_corpus sees it: level and heading the way seed stores them."""
    clauses = {}
    for c in json.loads(DOC_102.read_text(encoding="utf-8"))["clause"]:
        level = infer_level(c["numbering"])
        clauses[c["numbering"]] = {
            "numbering": c["numbering"],
            "level": level,
            "heading": c["text"].split("\n")[0] if level == "article" else None,
            "parent_id": c["parent_id"].split("#")[-1] if c["parent_id"] else None,
        }
    return clauses


def test_decision_wrapper_and_scope_articles_are_framing():
    clauses = _doc_102_clauses()
    framing = {n for n in clauses if is_framing(n, clauses)}
    assert {"QD.1", "QD.2", "1", "1.1", "1.2"} <= framing
    assert not framing & {"5", "5.2", "5.3", "5.6.a", "11.1", "12.2"}


def test_framing_clause_loses_to_the_rule_it_frames():
    # 1.1 "Quy định này điều chỉnh việc … rà soát định kỳ …" matches as well as 5.2 does.
    corpus = InternalCorpus(
        clauses={c: {"document_id": "DOC-102"} for c in ("1.1", "5.2")},
        bigrams={},
        idf={},
        framing={"1.1"},
    )
    entries = [
        {
            "clause_id": cid,
            "rrf": 0.03,
            "rrf_norm": 0.5,
            "ranks": {"sparse:legal_text": rank},
            "dense": None,
            "lex": {"shared": ["rà soát", "định kỳ"], "idf_score": 8.0, "ratio": 0.5},
        }
        for rank, cid in enumerate(("1.1", "5.2"), start=1)
    ]
    picked = select_candidates(entries, corpus, RetrievalParams())
    assert [c["clause_id"] for c in picked] == ["5.2"]
    kept = select_candidates(entries, corpus, RetrievalParams(framing_penalty=1.0))
    assert [c["clause_id"] for c in kept] == ["1.1", "5.2"]
