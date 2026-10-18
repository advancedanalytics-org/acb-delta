import pytest

from app.config import get_settings
from app.ria import compare


@pytest.fixture(autouse=True)
def no_llm_cache(monkeypatch):
    # Unit tests talk to a monkeypatched LLM only; the DB cache belongs to integration tests.
    monkeypatch.setattr(get_settings(), "llm_cache_enabled", False)


INTERNAL_52 = "Đơn vị thực hiện rà soát hồ sơ khách hàng định kỳ 24 tháng."
REG_CLAUSE = (
    "Tổ chức tín dụng phải rà soát, cập nhật hồ sơ nhận biết khách hàng định kỳ tối đa\n"
    "12 tháng một lần."
)


def _obligation(text=REG_CLAUSE, modality="must"):
    return {
        "obligation_id": "REG@v1#2.1~o1",
        "text": text,
        "span_start": 0,
        "span_end": len(text),
        "subject": "Tổ chức tín dụng",
        "action": "rà soát",
        "object": "cập nhật hồ sơ nhận biết khách hàng",
        "modality": modality,
        "condition": None,
        "deadline": "tối đa 12 tháng",
        "exception": None,
    }


def _evidence(text):
    return {"span": (0, len(text)), "shared_terms": ["rà soát", "hồ sơ", "khách hàng"]}


def test_value_change_with_exact_spans():
    result = compare.rule_classify(_obligation(), REG_CLAUSE, INTERNAL_52, _evidence(INTERNAL_52))
    assert result["category"] == "VALUE_CHANGE"
    assert result["target_span"] == {"text": "24 tháng", "start": 50, "end": 58}
    assert "12 tháng" in result["source_span"]["text"]
    src = result["source_span"]
    assert REG_CLAUSE[src["start"] : src["end"]] == src["text"]
    assert result["checks"][0] == {
        "check": "deterministic_values",
        "status": "fail",
        "detail": ["tối đa\n12 tháng (max) vs 24 tháng → conflict"],
    }


def test_stricter_internal_value_is_equivalent():
    internal = "Đối với khách hàng rủi ro cao, thời hạn rà soát định kỳ là 6 tháng."
    result = compare.rule_classify(_obligation(), REG_CLAUSE, internal, _evidence(internal))
    assert result["category"] == "EQUIVALENT"


def test_permission_conflict_needs_same_action():
    obligation = _obligation(
        "Không được cung cấp dịch vụ khi chưa hoàn thành nhận biết khách hàng.", "must_not"
    )
    obligation["action"], obligation["object"] = "cung cấp", "dịch vụ khi chưa hoàn thành"
    evidence = {"span": (0, 10), "shared_terms": ["cung cấp", "dịch vụ", "khách hàng"]}
    allowed = "Đơn vị có thể cung cấp dịch vụ cho khách hàng trước khi hoàn thiện hồ sơ."
    result = compare.rule_classify(obligation, obligation["text"], allowed, evidence)
    assert result["category"] == "CONTRADICTION"

    unrelated = "Khách hàng được phép cư trú tại Việt Nam, cung cấp dịch vụ theo hợp đồng."
    result = compare.rule_classify(obligation, obligation["text"], unrelated, evidence)
    assert result["category"] == "INDIRECT_IMPACT"


def test_llm_cannot_downgrade_rule_conflict(monkeypatch):
    monkeypatch.setattr(
        compare.llm,
        "chat_json",
        lambda *a, **k: {
            "classification": "EQUIVALENT",
            "rationale": "giống nhau",
            "source_quote": "12 tháng",
            "target_quote": "24 tháng",
            "confidence": 0.9,
        },
    )
    internal = {"clause_id": "DOC-102@v4#5.2", "text": INTERNAL_52}
    result = compare.classify(
        _obligation(), REG_CLAUSE, internal, _evidence(INTERNAL_52), [], use_llm=True
    )
    assert result["category"] == "VALUE_CHANGE"
    assert {"check": "verifier_agreement", "status": "fail"}.items() <= next(
        c for c in result["checks"] if c["check"] == "verifier_agreement"
    ).items()


def test_llm_ungrounded_quote_is_flagged(monkeypatch):
    monkeypatch.setattr(
        compare.llm,
        "chat_json",
        lambda *a, **k: {
            "classification": "ADDITION",
            "rationale": "x",
            "source_quote": "trích dẫn bịa",
            "target_quote": "24 tháng",
        },
    )
    internal = {"clause_id": "DOC-102@v4#5.2", "text": INTERNAL_52}
    result = compare.classify(
        _obligation(), REG_CLAUSE, internal, _evidence(INTERNAL_52), [], use_llm=True
    )
    grounding = next(c for c in result["checks"] if c["check"] == "source_grounding")
    assert grounding["status"] == "fail"
    assert result["category"] == "VALUE_CHANGE"  # rule result kept


def test_llm_grounded_answer_is_used(monkeypatch):
    internal_text = "Đơn vị lưu trữ hồ sơ khách hàng trên hệ thống."
    monkeypatch.setattr(
        compare.llm,
        "chat_json",
        lambda *a, **k: {
            "classification": "ADDITION",
            "rationale": "Nguồn thêm yêu cầu cập nhật định kỳ.",
            "source_quote": "cập nhật hồ sơ nhận biết khách hàng",
            "target_quote": "lưu trữ hồ sơ khách hàng",
            "confidence": 0.8,
        },
    )
    internal = {"clause_id": "DOC-102@v4#10.2", "text": internal_text}
    obligation = _obligation("Tổ chức tín dụng phải cập nhật hồ sơ nhận biết khách hàng.")
    result = compare.classify(
        obligation, obligation["text"], internal, _evidence(internal_text), [], use_llm=True
    )
    assert result["category"] == "ADDITION" and result["method"] == "llm+rule"
    assert result["target_span"]["text"] == "lưu trữ hồ sơ khách hàng"


def test_llm_agreeing_on_value_change_keeps_rule_spans(monkeypatch):
    monkeypatch.setattr(
        compare.llm,
        "chat_json",
        lambda *a, **k: {
            "classification": "VALUE_CHANGE",
            "rationale": "Nguồn tối đa 12 tháng, nội bộ 24 tháng.",
            "source_quote": REG_CLAUSE,
            "target_quote": INTERNAL_52,
            "confidence": 0.95,
        },
    )
    internal = {"clause_id": "DOC-102@v4#5.2", "text": INTERNAL_52}
    result = compare.classify(
        _obligation(), REG_CLAUSE, internal, _evidence(INTERNAL_52), [], use_llm=True
    )
    assert result["category"] == "VALUE_CHANGE" and result["method"] == "llm+rule"
    assert result["target_span"]["text"] == "24 tháng"
    assert result["rationale"].startswith("Nguồn tối đa")


def test_llm_ungrounded_is_retried_once(monkeypatch):
    answers = iter(
        [
            {"classification": "ADDITION", "source_quote": "bịa", "target_quote": "bịa"},
            {
                "classification": "VALUE_CHANGE",
                "source_quote": "12 tháng",
                "target_quote": "24 tháng",
                "rationale": "ok",
            },
        ]
    )
    monkeypatch.setattr(compare.llm, "chat_json", lambda *a, **k: next(answers))
    internal = {"clause_id": "DOC-102@v4#5.2", "text": INTERNAL_52}
    result = compare.classify(
        _obligation(), REG_CLAUSE, internal, _evidence(INTERNAL_52), [], use_llm=True
    )
    grounding = next(c for c in result["checks"] if c["check"] == "source_grounding")
    assert grounding["status"] == "pass"


def test_group_judge_one_call_for_all_candidates(monkeypatch):
    calls = []

    def fake(system, user, timeout=120):
        calls.append(user)
        return {
            "best": "DOC-102@v4#5.2",
            "results": [
                {
                    "ma": "DOC-102@v4#5.2",
                    "classification": "VALUE_CHANGE",
                    "rationale": "12 vs 24 tháng",
                    "source_quote": "12 tháng",
                    "target_quote": "24 tháng",
                    "confidence": 0.9,
                },
                {
                    "ma": "DOC-102@v4#10.2",
                    "classification": "INDIRECT_IMPACT",
                    "rationale": "liên quan lưu trữ",
                    "source_quote": "hồ sơ nhận biết khách hàng",
                    "target_quote": "lưu trữ hồ sơ",
                    "confidence": 0.4,
                },
            ],
        }

    monkeypatch.setattr(compare.llm, "chat_json", fake)
    items = [
        {
            "internal": {"clause_id": "DOC-102@v4#5.2", "text": INTERNAL_52},
            "evidence": _evidence(INTERNAL_52),
            "context": [],
        },
        {
            "internal": {
                "clause_id": "DOC-102@v4#10.2",
                "text": "Đơn vị lưu trữ hồ sơ trên hệ thống.",
            },
            "evidence": _evidence("x"),
            "context": [],
        },
    ]
    results, stats = compare.judge_group(_obligation(), REG_CLAUSE, items, use_llm=True)
    assert len(calls) == 1 and stats["llm_calls"] == 1
    assert [r["category"] for r in results] == ["VALUE_CHANGE", "INDIRECT_IMPACT"]
    assert results[0]["llm_best"] and not results[1]["llm_best"]
    assert results[0]["target_span"]["text"] == "24 tháng"  # rule span kept on agreement


def test_group_judge_retries_only_ungrounded(monkeypatch):
    answers = iter(
        [
            {
                "results": [
                    {
                        "ma": "A",
                        "classification": "ADDITION",
                        "source_quote": "bịa",
                        "target_quote": "x",
                    },
                    {
                        "ma": "B",
                        "classification": "EQUIVALENT",
                        "source_quote": "12 tháng",
                        "target_quote": "lưu trữ",
                        "rationale": "ok",
                    },
                ]
            },
            {
                "results": [
                    {
                        "ma": "A",
                        "classification": "VALUE_CHANGE",
                        "source_quote": "12 tháng",
                        "target_quote": "24 tháng",
                        "rationale": "ok",
                    },
                    {
                        "ma": "B",
                        "classification": "ADDITION",
                        "source_quote": "12 tháng",
                        "target_quote": "lưu trữ",
                    },
                ]
            },
        ]
    )
    refreshes = []

    def fake_cached(kind, system, user, refresh=False):
        refreshes.append(refresh)
        return next(answers), False

    monkeypatch.setattr(compare.llm, "chat_json_cached", fake_cached)
    items = [
        {
            "internal": {"clause_id": "A", "text": INTERNAL_52},
            "evidence": _evidence(INTERNAL_52),
            "context": [],
        },
        {
            "internal": {"clause_id": "B", "text": "Đơn vị lưu trữ hồ sơ."},
            "evidence": _evidence("x"),
            "context": [],
        },
    ]
    results, stats = compare.judge_group(_obligation(), REG_CLAUSE, items, use_llm=True)
    assert refreshes == [False, True] and stats["llm_calls"] == 2
    assert results[0]["category"] == "VALUE_CHANGE"
    assert results[1]["category"] == "EQUIVALENT"  # first grounded answer for B is kept
