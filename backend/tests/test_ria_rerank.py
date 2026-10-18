from app.config import get_settings
from app.ria import rerank
from app.ria.retrieval import InternalCorpus, RetrievalParams, select_candidates


class _Resp:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_rerank_client_orders_scores_by_input(monkeypatch):
    sent = {}
    monkeypatch.setattr(get_settings(), "rerank_base_url", "https://example.test/api/v1")
    monkeypatch.setattr(get_settings(), "rerank_model", "qwen/qwen3-reranker-8b")
    monkeypatch.setattr(get_settings(), "rerank_backend", "rerank")

    def fake_post(url, headers, json, timeout):
        sent.update(url=url, body=json)
        return _Resp(
            {
                "results": [
                    {"index": 1, "relevance_score": 0.1},
                    {"index": 0, "relevance_score": 0.9},
                ]
            }
        )

    monkeypatch.setattr("app.ria.http_retry.httpx.post", fake_post)
    assert rerank.rerank("q", ["a", "b"]) == [0.9, 0.1]
    assert sent["url"] == "https://example.test/api/v1/rerank"
    assert sent["body"]["model"] == "qwen/qwen3-reranker-8b" and sent["body"]["top_n"] == 2


def _entry(cid, rrf, shared=(), dense=None):
    return {
        "clause_id": cid,
        "rrf": rrf,
        "rrf_norm": rrf * 10,
        "ranks": {"sparse:legal_text": 1},
        "dense": dense,
        "lex": {"shared": list(shared), "idf_score": 3.0 * len(shared), "ratio": 0.5},
    }


CORPUS = InternalCorpus(
    clauses={c: {"document_id": "DOC-102"} for c in ("A", "B", "C")}, bigrams={}, idf={}
)


def test_rerank_scores_replace_the_gate():
    entries = [
        _entry("A", 0.05),
        _entry("B", 0.04, shared=("rà soát", "hồ sơ", "khách hàng")),
        _entry("C", 0.03),
    ]
    params = RetrievalParams(rerank_min_score=0.3, relative_cutoff=0.5)
    # A has no shared terms (gate would drop it) but the reranker keeps it; B fails the reranker.
    picked = select_candidates(entries, CORPUS, params, {"A": 0.82, "B": 0.1, "C": 0.5})
    assert [c["clause_id"] for c in picked] == ["A", "C"]
    assert picked[0]["score"] == 0.82 and picked[0]["rerank"] == 0.82
    # Without rerank scores the lexical gate decides.
    gated = select_candidates(entries, CORPUS, params)
    assert [c["clause_id"] for c in gated] == ["B"]


def test_transient_errors_are_retried(monkeypatch):
    from app.ria import http_retry

    statuses = iter([503, 200])

    class R(_Resp):
        def __init__(self, code):
            super().__init__({"ok": True})
            self.status_code = code

    monkeypatch.setattr(http_retry.time, "sleep", lambda s: None)
    monkeypatch.setattr(http_retry.httpx, "post", lambda *a, **k: R(next(statuses)))
    assert http_retry.post_json("u", headers={}, json={}, timeout=1) == {"ok": True}
