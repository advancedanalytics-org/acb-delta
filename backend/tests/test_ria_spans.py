from app.ria import compare, spans

SRC = (
    "Tổ chức tín dụng phải rà soát, cập nhật hồ sơ nhận biết khách hàng định kỳ tối đa "
    "12 tháng một lần."
)
TGT = (
    "Rà soát hồ sơ định kỳ nhằm bảo đảm thông tin chính xác. "
    "Đơn vị thực hiện rà soát hồ sơ khách hàng định kỳ 24 tháng."
)


def test_span_diff_aligns_best_sentence_and_types_the_value_change():
    d = spans.span_diff(SRC, TGT)
    assert d["target_sentence"]["text"].startswith("Đơn vị thực hiện")
    value = [x for x in d["diffs"] if "VALUE" in x["types"]]
    assert value and value[0]["target"]["text"] == "24"
    for x in d["diffs"]:  # offsets index the original strings
        t, s = x["target"], x["source"]
        assert TGT[t["start"] : t["end"]] == t["text"]
        assert SRC[s["start"] : s["end"]] == s["text"]
    tagged = {s["type"]: s["text"] for s in d["target_spans"]}
    assert tagged["VALUE"] == "24 tháng" and tagged["ACTOR"] == "Đơn vị"


def test_typed_target_span_narrows_a_broad_quote():
    d = spans.span_diff(SRC, TGT)
    sentence = d["target_sentence"]
    snapped = spans.typed_target_span(d, (sentence["start"], sentence["end"]), ("VALUE",))
    assert snapped and TGT[snapped["start"] : snapped["end"]] == "24"


def test_exception_only_in_source_is_a_scope_change():
    obligation_text = (
        "Ngân hàng không được cung cấp dịch vụ khi chưa hoàn thành nhận biết khách hàng, "
        "trừ trường hợp pháp luật cho phép hoàn thiện sau."
    )
    internal = "Ngân hàng không cung cấp dịch vụ khi chưa hoàn thành nhận biết khách hàng bắt buộc."
    obligation = {
        "text": obligation_text,
        "span_start": 0,
        "span_end": len(obligation_text),
        "modality": "must_not",
        "action": "cung cấp",
        "object": "dịch vụ",
    }
    diff = spans.span_diff(obligation_text, internal)
    assert "EXCEPTION" in diff["only_in_source"] and diff["similarity"] >= 0.5
    result = compare.rule_classify(
        obligation, obligation_text, internal, {"span": (0, 10), "shared_terms": []}, diff
    )
    assert result["category"] == "SCOPE_CHANGE"
    assert any(c["check"] == "span_diff" for c in result["checks"])


def test_unrelated_sentences_are_not_scope_changes():
    diff = spans.span_diff(
        "Ngân hàng phải lưu trữ hồ sơ tối thiểu 10 năm, trừ trường hợp pháp luật quy định khác.",
        "Khối Tuân thủ tổng hợp báo cáo hằng quý.",
    )
    assert diff["similarity"] < compare.SCOPE_MIN_SIMILARITY
    assert compare._scope_difference(diff) is None
