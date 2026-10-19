import math

from app.ria import retrieval
from app.ria.indexing import article_of, mean_vector


def _clause(cid, parent, level, text="Đơn vị rà soát hồ sơ khách hàng."):
    return {"clause_id": cid, "parent_id": parent, "level": level, "text": text}


CLAUSES = {
    c["clause_id"]: c
    for c in (
        _clause("D#C1", None, "chapter", "Chương I"),
        _clause("D#5", "D#C1", "article", "Rà soát hồ sơ"),
        _clause("D#5.1", "D#5", "clause"),
        _clause("D#5.1.a", "D#5.1", "point"),
        _clause("D#5.2", "D#5", "clause"),
        _clause("D#6", "D#C1", "article"),
    )
}


def test_article_of_walks_up_to_the_article():
    assert article_of(CLAUSES["D#5.1.a"], CLAUSES) == "D#5"
    assert article_of(CLAUSES["D#5"], CLAUSES) == "D#5"
    assert article_of(CLAUSES["D#C1"], CLAUSES) is None


def test_mean_vector_is_unit_length():
    v = mean_vector([[1.0, 0.0], [0.0, 1.0]])
    assert math.isclose(v[0], v[1]) and math.isclose(math.hypot(*v), 1.0)


def test_article_members_in_document_order():
    children = {}
    for c in CLAUSES.values():
        if c["parent_id"]:
            children.setdefault(c["parent_id"], []).append(c["clause_id"])
    corpus = retrieval.InternalCorpus(CLAUSES, {}, {}, children)
    assert retrieval.article_members("D#5", corpus) == ["D#5", "D#5.1", "D#5.1.a", "D#5.2"]


def test_article_lists_count_as_dense_evidence():
    fused = retrieval.rrf(
        {"article:legal_text": [("D#5.2", 0.66)], "sparse:legal_text": [("D#5.2", 3.0)]}, 60
    )
    assert fused["D#5.2"]["dense"] == 0.66
    assert set(fused["D#5.2"]["ranks"]) == {"article:legal_text", "sparse:legal_text"}


def test_article_origin_only_covers_returned_clauses(monkeypatch):
    # An article larger than candidates_per_query: clauses cut from the list must not keep an
    # article score, or fuse_for_obligation looks them up in the fused results and fails.
    clauses = {"D#5": _clause("D#5", None, "article")}
    clauses.update({f"D#5.{i}": _clause(f"D#5.{i}", "D#5", "clause") for i in range(1, 8)})
    children = {"D#5": [f"D#5.{i}" for i in range(1, 8)]}
    corpus = retrieval.InternalCorpus(clauses, {}, {}, children)

    def fake_dense(conn, vector, model, corpus, limit, view="context", ids=None):
        if view == "article":
            return [("D#5", 0.8)]
        return [(cid, 0.9 - i / 100) for i, cid in enumerate(ids)][:limit]

    monkeypatch.setattr(retrieval, "_dense", fake_dense)
    params = retrieval.RetrievalParams(candidates_per_query=3)
    ranked, origin = retrieval._dense_articles(None, [1.0], "m", corpus, params)
    assert len(ranked) == 3
    assert set(origin) == {cid for cid, _ in ranked}
