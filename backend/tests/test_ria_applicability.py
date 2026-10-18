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
