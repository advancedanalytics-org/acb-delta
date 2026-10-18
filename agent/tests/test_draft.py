from fastapi.testclient import TestClient

from agent import server
from agent.draft_graph import apply_patch, insert_text, locate_patch
from agent.schemas import PatchDraft, Span, Verdict

CLAUSE = "5.2. Hồ sơ nhận biết khách hàng được rà soát, cập nhật định kỳ 24 tháng một lần."
START = CLAUSE.index("24 tháng")
TARGET = {"text": "24 tháng", "start": START, "end": START + len("24 tháng")}

REQUEST = {
    "finding_id": "RIA-test000001",
    "category": "VALUE_CHANGE",
    "rationale": "Quy định mới: tối đa 12 tháng; nội bộ: 24 tháng.",
    "obligation": {
        "clause_id": "REG-99-2026-TT-NHNN@v1#2.1",
        "text": "Tổ chức tín dụng phải rà soát, cập nhật hồ sơ định kỳ tối đa 12 tháng một lần.",
    },
    "source_span": {"text": "tối đa 12 tháng", "start": 60, "end": 75},
    "clause": {"clause_id": "DOC-102@v4#5.2", "numbering": "5.2", "text": CLAUSE},
    "target_span": TARGET,
    "citations": ["REG-99-2026-TT-NHNN@v1#2.1", "DOC-102@v4#5.2"],
}

GOOD_PATCH = {
    "operation": "REPLACE",
    "old_text": "24 tháng",
    "new_text": "tối đa 12 tháng",
    "rationale": "Giảm chu kỳ rà soát theo Thông tư 99.",
}
AGREE = {
    "satisfies_obligation": True,
    "preserves_other_content": True,
    "adds_no_exception": True,
    "comment": "Đúng nghĩa vụ.",
}


def post(request=REQUEST):
    response = TestClient(server.create_app()).post("/draft", json=request)
    assert response.status_code == 200, response.text
    return response.json()


def checks(body) -> dict[str, str]:
    return {c["check"]: c["status"] for c in body["verification"]["checks"]}


# --- locate_patch: pure rules ---


def test_locate_found_once():
    assert locate_patch(CLAUSE, "REPLACE", "24 tháng", None) == (START, START + 8)


def test_locate_tolerates_whitespace_differences():
    text = "định kỳ 24\ntháng một lần"
    start, end = locate_patch(text, "REPLACE", "24 tháng", None)
    assert text[start:end] == "24\ntháng"


def test_locate_not_found():
    assert locate_patch(CLAUSE, "REPLACE", "36 tháng", None).startswith("span_matches_source")


def test_locate_found_twice_is_rejected():
    text = "Hạn 24 tháng; gia hạn 24 tháng."
    assert locate_patch(text, "REPLACE", "24 tháng", None).startswith("span_unique")


def test_locate_found_twice_but_once_inside_target_span():
    text = "Hạn 24 tháng; gia hạn 24 tháng."
    second = text.rindex("24 tháng")
    target = Span(text="gia hạn 24 tháng", start=second - 8, end=second + 8)
    assert locate_patch(text, "REPLACE", "24 tháng", target) == (second, second + 8)


def test_locate_insert_at_target_end_or_clause_end():
    target = Span(**TARGET)
    assert locate_patch(CLAUSE, "INSERT", "", target) == (target.end, target.end)
    assert locate_patch(CLAUSE, "INSERT", "", None) == (len(CLAUSE), len(CLAUSE))


def test_locate_never_matches_inside_a_word():
    text = "Thời hạn xử lý 130 ngày."
    assert locate_patch(text, "REPLACE", "30 ngày", None).startswith("span_matches_source")
    assert locate_patch(text, "REPLACE", "130 ngày", None) == (15, 23)


def test_locate_counts_overlapping_repeats():
    assert locate_patch("Mục 1.1.1", "REPLACE", "1.1", None).startswith("span_unique")


def test_insert_text_adds_missing_spaces():
    assert insert_text("a 24 tháng.", 10, "kể từ ngày cấp") == " kể từ ngày cấp"
    assert insert_text("Câu một.", 8, " Câu hai.") == " Câu hai."
    assert insert_text("ab cd", 3, "X") == "X "


def test_apply_patch():
    assert apply_patch("ab24cd", 2, 4, "12") == "ab12cd"


# --- /draft graph with a fake LLM ---


def test_happy_path_replace(fake_llm):
    replies, calls = fake_llm
    replies[PatchDraft] = GOOD_PATCH
    replies[Verdict] = AGREE

    body = post()

    assert body["operation"] == "REPLACE"
    assert CLAUSE[body["start"] : body["end"]] == body["old_text"] == "24 tháng"
    assert body["new_text"] == "tối đa 12 tháng"
    assert body["verification"]["status"] == "review_required"
    assert checks(body) == {
        "span_matches_source": "pass",
        "span_unique": "pass",
        "inside_target_span": "pass",
        "minimal_change": "pass",
        "independent_verifier": "pass",
    }
    assert body["legal_evidence_ids"] == ["REG-99-2026-TT-NHNN@v1#2.1"]
    assert len(body["prompt_version"]) == 12
    # The verifier sees the patched clause, not the drafter's reasoning.
    verify_user = next(user for schema, user in calls if schema is Verdict)
    assert "định kỳ tối đa 12 tháng một lần" in verify_user


def test_text_not_in_clause_retries_once_then_fails(fake_llm):
    replies, calls = fake_llm
    replies[PatchDraft] = GOOD_PATCH | {"old_text": "36 tháng"}
    replies[Verdict] = AGREE

    body = post()

    assert [schema for schema, _ in calls] == [PatchDraft, PatchDraft]
    assert "Bản nháp trước bị từ chối" in calls[1][1]
    assert body["verification"]["status"] == "failed"
    assert body["verification"]["reason"].startswith("span_matches_source")
    assert body["start"] is None and body["old_text"] is None


def test_retry_succeeds_on_second_attempt(fake_llm):
    replies, calls = fake_llm
    attempts = iter([GOOD_PATCH | {"old_text": "36 tháng"}, GOOD_PATCH])
    replies[PatchDraft] = lambda user: next(attempts)
    replies[Verdict] = AGREE

    body = post()

    assert body["verification"]["status"] == "review_required"
    assert body["old_text"] == "24 tháng"


def test_edit_outside_target_span_fails(fake_llm):
    replies, _ = fake_llm
    replies[PatchDraft] = GOOD_PATCH | {"old_text": "Hồ sơ", "new_text": "Toàn bộ hồ sơ"}

    body = post()

    assert body["verification"]["status"] == "failed"
    assert body["verification"]["reason"].startswith("inside_target_span")


def test_no_op_patch_fails(fake_llm):
    replies, _ = fake_llm
    replies[PatchDraft] = GOOD_PATCH | {"new_text": "24 tháng"}

    assert post()["verification"]["reason"].startswith("minimal_change")


def test_verifier_disagrees_stays_review_required(fake_llm):
    replies, _ = fake_llm
    replies[PatchDraft] = GOOD_PATCH
    replies[Verdict] = AGREE | {"adds_no_exception": False, "comment": "Thêm ngoại lệ."}

    body = post()

    assert body["verification"]["status"] == "review_required"
    verifier = body["verification"]["checks"][-1]
    assert verifier == {
        "check": "independent_verifier",
        "status": "fail",
        "detail": "Thêm ngoại lệ.",
    }


def test_verifier_error_is_skipped_not_a_crash(fake_llm):
    replies, _ = fake_llm
    replies[PatchDraft] = GOOD_PATCH

    def boom(user):
        raise ValueError("bad json")

    replies[Verdict] = boom

    body = post()

    assert body["verification"]["status"] == "review_required"
    assert checks(body)["independent_verifier"] == "skipped"


def test_drafter_llm_error_is_a_failed_proposal(fake_llm):
    replies, _ = fake_llm

    def boom(user):
        raise ValueError("LLM returned no PatchDraft")

    replies[PatchDraft] = boom

    body = post()

    assert body["verification"]["status"] == "failed"
    assert "LLM error" in body["verification"]["reason"]


def test_insert_without_target_span(fake_llm):
    replies, _ = fake_llm
    replies[PatchDraft] = {
        "operation": "INSERT",
        "old_text": "",
        "new_text": " Kết quả rà soát được lưu trên hệ thống.",
        "rationale": "Nghĩa vụ lưu trữ mới.",
    }
    replies[Verdict] = AGREE

    body = post(REQUEST | {"category": "ADDITION", "target_span": None})

    assert (body["start"], body["end"], body["old_text"]) == (len(CLAUSE), len(CLAUSE), "")
    assert checks(body)["inside_target_span"] == "skipped"
    assert body["verification"]["status"] == "review_required"


def test_draft_without_llm_config_is_503(monkeypatch):
    from agent.config import get_settings

    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setenv("LLM_MODEL", "")
    get_settings.cache_clear()

    response = TestClient(server.create_app()).post("/draft", json=REQUEST)

    assert response.status_code == 503
    get_settings.cache_clear()


def test_target_span_must_match_clause_text():
    client = TestClient(server.create_app())
    for bad in (
        TARGET | {"start": -3, "end": -3},
        TARGET | {"end": 999},
        TARGET | {"text": "36 tháng"},
    ):
        assert client.post("/draft", json=REQUEST | {"target_span": bad}).status_code == 422
