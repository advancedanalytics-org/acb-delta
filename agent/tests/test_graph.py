import pytest

from agent.graph import build_graph
from agent.schemas import ChangeList, ImpactJudgement

CHANGES = [
    {"clause": "Khoản 2 Điều 9", "kind": "amended", "text": "Thời hạn cho vay tiêu dùng 60 tháng."},
    {"clause": "Khoản 3 Điều 9", "kind": "amended", "text": "Thời hạn cho vay mua nhà 25 năm."},
]


def run(text="Thông tư 31/2026/TT-NHNN\nĐiều 9. Thời hạn cho vay", graph=None):
    graph = graph or build_graph()
    return graph.invoke({"vbpl_text": text}, config={"configurable": {"thread_id": "test"}})


@pytest.mark.usefixtures("corpus")
def test_fan_out_runs_one_branch_per_change_and_merges_impacts(fake_llm):
    replies, calls = fake_llm
    replies[ChangeList] = {"changes": CHANGES}

    result = run()

    assert result["changes"] == CHANGES
    # Both changes match the loan-term passage; each branch contributes one impact.
    assert sorted(i["change_clause"] for i in result["impacts"]) == sorted(
        c["text"] for c in CHANGES
    )
    impact = result["impacts"][0]
    assert impact["chunk_id"] == "doc-cv:1:1"
    assert impact["affected_text"] == "Thời hạn cho vay tiêu dùng tối đa là 84 tháng."
    assert impact["suggested_text"].endswith("60 tháng.")
    assert impact["page"] is None and impact["bboxes"] == []
    assert any("VBPL mới: Thông tư 31/2026/TT-NHNN" in user for _, user in calls)
    # Two branches, each judging both corpus passages.
    assert sum(schema is ImpactJudgement for schema, _ in calls) == 4


@pytest.mark.usefixtures("corpus")
def test_runs_on_the_same_thread_do_not_accumulate(fake_llm):
    replies, _ = fake_llm
    replies[ChangeList] = {"changes": CHANGES[:1]}
    graph = build_graph()

    first = run(graph=graph)
    second = run(graph=graph)

    assert len(first["impacts"]) == len(second["impacts"]) == 1


@pytest.mark.usefixtures("corpus")
def test_unaffected_candidates_are_dropped(fake_llm):
    replies, calls = fake_llm
    replies[ChangeList] = {
        "changes": [{"clause": "Điều 10", "kind": "added", "text": "Hạn mức cho vay tín chấp."}]
    }

    result = run()

    # Both passages are retrieved and judged; only the loan-term one is affected.
    assert sum(schema is ImpactJudgement for schema, _ in calls) == 2
    assert [i["chunk_id"] for i in result["impacts"]] == ["doc-cv:1:1"]


@pytest.mark.usefixtures("corpus")
def test_no_changes_ends_without_impacts(fake_llm):
    _, calls = fake_llm

    result = run()

    assert result["changes"] == []
    assert result.get("impacts", []) == []
    assert [schema for schema, _ in calls] == [ChangeList]


@pytest.mark.usefixtures("corpus")
def test_changes_are_capped(fake_llm, monkeypatch):
    from agent.config import get_settings

    replies, _ = fake_llm
    replies[ChangeList] = {"changes": CHANGES}
    monkeypatch.setenv("MAX_CHANGES", "1")
    get_settings.cache_clear()

    result = run()

    assert result["changes"] == CHANGES[:1]
    assert len(result["impacts"]) == 1
