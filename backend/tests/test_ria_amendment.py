from app.config import get_settings
from app.ria import amendment, jev

CLAUSE = "Đơn vị thực hiện rà soát hồ sơ khách hàng định kỳ 24 tháng."
OBLIGATION = (
    "Tổ chức tín dụng phải rà soát, cập nhật hồ sơ nhận biết khách hàng định kỳ tối đa\n"
    "12 tháng một lần."
)


def _finding(**over):
    f = {
        "finding_id": "RIA-1",
        "category": "VALUE_CHANGE",
        "source_span": {"text": "tối đa\n12 tháng", "start": 75, "end": 90},
        "target_span": {"text": "24 tháng", "start": 50, "end": 58},
        "clause_text": CLAUSE,
        "obligation_text": OBLIGATION,
        "regulation_clause_id": "REG@v1#2.1",
        "regulation_status": "effective",
        "condition": None,
        "exception": None,
    }
    f.update(over)
    return f


def _amendment(patch: dict) -> dict:
    return {
        "operation": patch["operation"],
        "target_start": patch["start"],
        "target_end": patch["end"],
        "before_text": patch["before"],
        "after_text": patch["after"],
        "original_hash": amendment.sha256(CLAUSE),
    }


def test_value_change_gets_a_minimal_rule_patch():
    patch = amendment._rule_patch(_finding())
    assert patch["operation"] == "REPLACE" and patch["method"] == "rule"
    assert (patch["start"], patch["end"], patch["before"]) == (50, 58, "24 tháng")
    assert patch["after"] == "tối đa 12 tháng"
    a = _amendment(patch)
    assert amendment.apply_patch(CLAUSE, a).endswith("định kỳ tối đa 12 tháng.")


def test_checks_pass_for_the_rule_patch_without_a_verifier(monkeypatch):
    monkeypatch.setattr(get_settings(), "jev_model", "")
    a = _amendment(amendment._rule_patch(_finding()))
    checks = amendment.run_checks(_finding(), a, CLAUSE, "effective")
    by = {c["check"]: c["status"] for c in checks}
    assert by["source_grounding"] == by["patch_integrity"] == by["minimality"] == "pass"
    assert by["deterministic_values"] == "pass"
    assert by["semantic_entailment"] == "skipped"
    assert amendment.overall(checks) == "NEEDS_HUMAN_REVIEW"


def test_changed_clause_blocks_the_patch():
    a = _amendment(amendment._rule_patch(_finding()))
    checks = amendment.run_checks(_finding(), a, CLAUSE.replace("24", "36"), "effective")
    assert amendment.overall(checks) == "BLOCKED"


def test_wrong_value_and_large_rewrite_are_blocked(monkeypatch):
    monkeypatch.setattr(get_settings(), "jev_model", "")
    wrong = _amendment(
        {"operation": "REPLACE", "start": 50, "end": 58, "before": "24 tháng", "after": "18 tháng"}
    )
    checks = amendment.run_checks(_finding(), wrong, CLAUSE, "effective")
    assert {c["check"]: c["status"] for c in checks}["deterministic_values"] == "block"
    rewrite = _amendment(
        {"operation": "REPLACE", "start": 0, "end": len(CLAUSE), "before": CLAUSE, "after": "Mới."}
    )
    checks = amendment.run_checks(_finding(), rewrite, CLAUSE, "effective")
    assert {c["check"]: c["status"] for c in checks}["minimality"] == "block"


def test_independent_verifier_can_fail_the_patch(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "jev_base_url", "https://openrouter.test/api/alpha")
    monkeypatch.setattr(s, "jev_model", "typesafe/jev-1.14")
    monkeypatch.setattr(
        jev,
        "post_json",
        lambda *a, **k: {
            "answers": {
                "satisfies": {"type": "noul", "noul": 0.2},
                "no_new_obligation": {"type": "noul", "noul": 0.9},
                "preserves_rest": {"type": "noul", "noul": 0.9},
            }
        },
    )
    a = _amendment(amendment._rule_patch(_finding()))
    checks = amendment.run_checks(_finding(), a, CLAUSE, "effective")
    entail = next(c for c in checks if c["check"] == "semantic_entailment")
    assert entail["status"] == "fail" and entail["detail"]["scores"]["satisfies"] == 0.2
    assert amendment.overall(checks) == "BLOCKED"


def test_llm_patch_requires_a_unique_locator(monkeypatch):
    answers = iter(
        [
            {"operation": "REPLACE", "old_text": "hồ sơ", "new_text": "x"},  # not unique? once
            {"operation": "REPLACE", "old_text": "không có", "new_text": "x"},
        ]
    )
    monkeypatch.setattr(amendment.llm, "chat_json_cached", lambda *a, **k: (next(answers), False))
    f = _finding(category="SCOPE_CHANGE", condition=None, exception=None)
    f.update(
        rationale="r",
        regulation_clause_text=OBLIGATION,
        internal_clause_id="DOC@v1#5.2",
        clause_text="hồ sơ khách hàng và hồ sơ đơn vị",
    )
    try:
        amendment._llm_patch(f, refresh=False)
    except amendment.AmendmentError as exc:
        assert exc.status_code == 422 and "unique" in exc.detail
    else:
        raise AssertionError("ambiguous locator must be rejected")


def test_broad_llm_quote_is_not_a_rule_patch():
    f = _finding(
        source_span={"text": OBLIGATION, "start": 0, "end": len(OBLIGATION)},
        target_span={"text": "24", "start": 50, "end": 52},
    )
    assert amendment._rule_patch(f) is None
