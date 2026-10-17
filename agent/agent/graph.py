"""Impact-analysis graph: VBPL text in, affected internal passages + suggested edits out."""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.nodes import draft_amendment, extract_changes, judge_impact, retrieve
from agent.state import ImpactState


def build_graph() -> CompiledStateGraph:
    graph = StateGraph(ImpactState)
    graph.add_node("extract_changes", extract_changes)
    graph.add_node("retrieve", retrieve)
    graph.add_node("judge_impact", judge_impact)
    graph.add_node("draft_amendment", draft_amendment)

    # Linear for now. TAI-01 replaces extract_changes → retrieve with a `Send` fan-out per change;
    # TAI-02 adds `interrupt()` so a reviewer accepts / edits / rejects each draft.
    graph.add_edge(START, "extract_changes")
    graph.add_edge("extract_changes", "retrieve")
    graph.add_edge("retrieve", "judge_impact")
    graph.add_edge("judge_impact", "draft_amendment")
    graph.add_edge("draft_amendment", END)

    # In-memory checkpointer keyed by AgentBase session id; nothing persists across restarts.
    return graph.compile(checkpointer=InMemorySaver())
