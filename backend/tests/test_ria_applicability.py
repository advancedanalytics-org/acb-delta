from app.ria import applicability


class _Conn:
    def __init__(self):
        self.updates = []

    def execute(self, stmt, rows):
        self.updates.extend(rows)


def _o(oid, subject, stored=None):
    return {
        "obligation_id": oid,
        "subject": subject,
        "text": f"{subject} phải làm việc X.",
        "article_heading": None,
        "applicability": stored,
    }


def test_rules_settle_clear_subjects():
    assert applicability.rule_decision(_o("1", "Bộ Công an"))[0] == "no"
    assert applicability.rule_decision(_o("2", "Chủ thể dữ liệu cá nhân"))[0] == "no"
    assert applicability.rule_decision(_o("3", "Tổ chức tín dụng"))[0] == "yes"
    assert applicability.rule_decision(_o("4", "Cơ quan, tổ chức, cá nhân"))[0] == "yes"
    assert applicability.rule_decision(_o("5", "Nhà cung cấp hệ thống trí tuệ nhân tạo")) is None


def test_llm_decides_the_rest_in_batches_and_results_are_stored(monkeypatch):
    asked = []

    def fake(kind, system, user, refresh=False):
        asked.append(user)
        return {
            "items": [
                {"id": "5", "applies": "no", "reason": "ngân hàng không cung cấp AI"},
                {"id": "6", "applies": "maybe"},
            ]
        }, False

    monkeypatch.setattr(applicability.llm, "chat_json_cached", fake)
    conn = _Conn()
    obligations = [
        _o("1", "Bộ Công an"),
        _o("3", "Tổ chức tín dụng"),
        _o("5", "Nhà cung cấp hệ thống trí tuệ nhân tạo"),
        _o("6", "Người có thẩm quyền"),
        _o("7", "Ai đó", stored="yes"),
    ]
    result = applicability.classify_obligations(conn, obligations, use_llm=True)
    assert result == {"1": "no", "3": "yes", "5": "no", "6": "uncertain", "7": "yes"}
    assert len(asked) == 1  # one batch for the two undecided obligations
    stored = {u["id"]: (u["a"], u["m"]) for u in conn.updates}
    assert stored["1"] == ("no", "rule") and stored["5"][0] == "no"
    assert "6" not in stored  # invalid answer: undecided, asked again next run
    assert "7" not in stored  # already stored: reused, not re-asked


def test_without_llm_unclear_obligations_stay_in_scope():
    conn = _Conn()
    result = applicability.classify_obligations(conn, [_o("5", "Nhà cung cấp")], use_llm=False)
    assert result == {"5": "uncertain"} and conn.updates == []


def _point(oid, text, subject="", action="", method="rule", stored=None):
    return {
        "obligation_id": oid,
        "subject": subject,
        "action": action,
        "object": "",
        "condition": None,
        "deadline": None,
        "exception": None,
        "text": text,
        "parent_text": "Bên kiểm soát dữ liệu cá nhân có trách nhiệm sau đây:",
        "article_heading": "Điều 9. Trách nhiệm",
        "extraction_method": method,
        "applicability": stored,
    }


def test_refine_applies_only_verbatim_fields_and_stores_them(monkeypatch):
    asked = []

    def fake(kind, system, user, refresh=False):
        asked.append(kind)
        return {
            "items": [
                {
                    "id": "p1",
                    "subject": "Bên kiểm soát dữ liệu cá nhân",  # from the lead-in
                    "action": "lưu trữ",
                    "object": "nhật ký xử lý dữ liệu cá nhân",
                    "condition": None,
                    "deadline": "02 năm",
                    "exception": "trừ khi được miễn trừ",  # not in the text: rejected
                    "applies": "uncertain",
                },
                {"id": "p2", "subject": "b)", "action": "chuyển", "applies": "no"},
                {"id": "p3", "applies": "yes", "subject": 42},  # invalid item: dropped
            ]
        }, False

    monkeypatch.setattr(applicability.llm, "chat_json_cached", fake)
    monkeypatch.setattr(applicability.llm, "llm_model", lambda: "m")
    conn = _Conn()
    p1 = _point("p1", "Lưu trữ nhật ký xử lý dữ liệu cá nhân trong 02 năm;", action="a lưu")
    p2 = _point("p2", "Không được chuyển dữ liệu ra nước ngoài;", subject="Nhà cung cấp X")
    p3 = _point("p3", "Báo cáo cơ quan chuyên trách;")
    done = _point("p4", "Đã tách.", subject="Ai đó", method="rule+llm:m", stored="yes")
    stats = applicability.Counter()
    result = applicability.classify_obligations(
        conn, [p1, p2, p3, done], use_llm=True, refine=True, stats=stats
    )

    assert asked == ["obligation_refine"]  # one combined call, p4 already refined
    assert p1["subject"] == "Bên kiểm soát dữ liệu cá nhân" and p1["action"] == "lưu trữ"
    assert p1["object"] == "nhật ký xử lý dữ liệu cá nhân" and p1["deadline"] == "02 năm"
    assert p1["exception"] is None
    assert p2["subject"] == "Nhà cung cấp X"  # "b)" is not verbatim words of the text
    # p1's refined subject is a controller, so the rule decides it; p2 keeps the LLM's "no".
    assert result == {"p1": "yes", "p2": "no", "p3": "uncertain", "p4": "yes"}
    refined_rows = {u["id"]: u for u in conn.updates if "rf" in u}
    assert set(refined_rows) == {"p1", "p2"}
    assert refined_rows["p1"]["m"] == "rule+llm:m"
    assert '"action": "a lưu"' in refined_rows["p1"]["rf"]
    assert stats["refined"] == 2 and stats["fields_rejected"] == 2


def test_refine_failure_keeps_rule_fields_and_scope(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(applicability.llm, "chat_json_cached", boom)
    conn = _Conn()
    o = _point("p1", "Lưu trữ nhật ký;", subject="Tổ chức tín dụng", action="a lưu")
    result = applicability.classify_obligations(conn, [o], use_llm=True, refine=True)
    assert result == {"p1": "yes"}  # the rule still decides on the rule subject
    assert o["action"] == "a lưu" and o["extraction_method"] == "rule"
    assert all("rf" not in u for u in conn.updates)
