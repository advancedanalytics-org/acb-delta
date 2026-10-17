from agent.graph import build_graph


def test_graph_runs_all_nodes_on_sample_input():
    graph = build_graph()
    config = {"configurable": {"thread_id": "test"}}

    result = graph.invoke({"vbpl_text": "Điều 1. Sửa đổi khoản 2 Điều 5."}, config=config)

    assert result["vbpl_text"].startswith("Điều 1")
    for key in ("changes", "candidates", "impacts", "amendments"):
        assert result[key] == []
    visited = {node for snapshot in graph.get_state_history(config) for node in snapshot.next}
    assert {"extract_changes", "retrieve", "judge_impact", "draft_amendment"} <= visited
