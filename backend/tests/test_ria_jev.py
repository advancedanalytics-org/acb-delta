from app.config import get_settings
from app.ria import jev, rerank


def _configure(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "jev_base_url", "https://openrouter.test/api/alpha")
    monkeypatch.setattr(s, "jev_model", "typesafe/jev-1.14")
    monkeypatch.setattr(s, "rerank_backend", "jev")


def test_jev_rerank_asks_one_choice_question_per_clause(monkeypatch):
    _configure(monkeypatch)
    sent = {}

    def fake_post(url, headers, json, timeout):
        sent.update(url=url, body=json)
        return {
            "answers": {
                "c0": {"type": "choice", "probabilities": {"same_activity": 0.96}},
                "c1": {"type": "choice", "probabilities": {"same_activity": 0.31}},
            }
        }

    monkeypatch.setattr(jev, "post_json", fake_post)
    assert rerank.backend() == "jev" and rerank.rerank_model() == "typesafe/jev-1.14"
    assert rerank.rerank("nghĩa vụ", ["điều A", "điều B"]) == [0.96, 0.31]
    assert sent["url"] == "https://openrouter.test/api/alpha/decisions"
    body = sent["body"]
    assert body["model"] == "typesafe/jev-1.14"
    assert body["state"]["dieu_khoan_noi_bo"] == {"c0": "điều A", "c1": "điều B"}
    assert {q["type"] for q in body["questions"].values()} == {"choice"}
    assert set(next(iter(body["questions"].values()))["criteria"]) == {
        "same_activity",
        "same_domain_only",
        "unrelated",
    }
    assert rerank.default_min_score() == rerank.DEFAULT_MIN_SCORE["jev"]


def test_jev_splits_large_question_sets(monkeypatch):
    _configure(monkeypatch)
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(len(json["questions"]))
        return {
            "answers": {
                k: {"type": "choice", "probabilities": {"same_activity": 0.5}}
                for k in json["questions"]
            }
        }

    monkeypatch.setattr(jev, "post_json", fake_post)
    scores = rerank.rerank("q", [f"d{i}" for i in range(30)])
    assert len(scores) == 30 and calls == [24, 6]


def test_missing_or_malformed_answers_score_zero(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(jev, "post_json", lambda *a, **k: {"answers": {"c0": {"type": "choice"}}})
    assert rerank.rerank("q", ["a", "b"]) == [0.0, 0.0]
    assert jev.probability({"type": "noul", "noul": "1.7"}) == 1.0


def test_backend_falls_back_when_jev_not_configured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "rerank_backend", "jev")
    monkeypatch.setattr(s, "jev_model", "")
    assert rerank.backend() is None and rerank.rerank_model() is None
