from app.ria.analysis import _finding_heads


def _pair(clause_id: str, category: str, score: float = 0.5, llm_best: bool = False):
    ev = {"evidence_id": f"EV-{clause_id}", "candidate": {"score": score}}
    return ev, {"category": category, "llm_best": llm_best}


def _heads(pairs):
    return [
        (head[0]["evidence_id"], [p[0]["evidence_id"] for p in others])
        for head, others in _finding_heads(pairs)
    ]


def test_every_conflicting_clause_is_its_own_finding():
    # 5.2 and 5.3 both say "24 tháng": patching only one leaves the document contradicting itself.
    pairs = [
        _pair("5.1", "EQUIVALENT", 0.9),
        _pair("5.2", "VALUE_CHANGE", 0.8),
        _pair("5.3", "VALUE_CHANGE", 0.4),
    ]
    assert _heads(pairs) == [
        ("EV-5.2", ["EV-5.3", "EV-5.1"]),
        ("EV-5.3", ["EV-5.2", "EV-5.1"]),
    ]


def test_scope_change_is_a_conflict_and_is_not_hidden_by_an_equivalent_clause():
    pairs = [_pair("A", "EQUIVALENT", 0.9), _pair("B", "SCOPE_CHANGE", 0.3)]
    assert _heads(pairs) == [("EV-B", ["EV-A"])]


def test_without_conflict_one_finding_and_satisfied_beats_addition():
    pairs = [
        _pair("A", "ADDITION", 0.9),
        _pair("B", "EQUIVALENT", 0.2),
        _pair("C", "ADDITION", 0.5, llm_best=True),
    ]
    assert _heads(pairs) == [("EV-B", ["EV-C", "EV-A"])]
    # Among equal categories the LLM's best match wins over a higher retrieval score.
    assert _heads(pairs[::2]) == [("EV-C", ["EV-A"])]
