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
