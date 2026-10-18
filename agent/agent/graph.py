"""Impact-analysis graph: VBPL text in, affected internal passages + suggested edits out."""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from agent.nodes import analyze_change, extract_changes
from agent.state import ImpactState


def fan_out_changes(state: ImpactState) -> list[Send]:
    """One analyze_change branch per change, run in parallel. No changes → no branch → END."""
    return [
        Send("analyze_change", {"change": change, "vbpl_text": state["vbpl_text"]})
        for change in state.get("changes", [])
    ]


def build_graph() -> CompiledStateGraph:
    graph = StateGraph(ImpactState)
    graph.add_node("extract_changes", extract_changes)
    graph.add_node("analyze_change", analyze_change)

    # HITL is not in the graph: it runs to the end and the backend stores impacts as pending.
    graph.add_edge(START, "extract_changes")
    graph.add_conditional_edges("extract_changes", fan_out_changes, ["analyze_change", END])
    graph.add_edge("analyze_change", END)

    # No checkpointer: every run starts clean. Saving state per AgentBase session id would make the
    # `impacts` reducer append a second run's results to the first's (and grow memory forever).
    return graph.compile()
