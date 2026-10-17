from agent import llm, prompts
from agent.config import get_settings
from agent.schemas import ChangeList
from agent.state import ImpactState


def extract_changes(state: ImpactState) -> ImpactState:
    """Split the VBPL into new / amended / repealed clauses (structured LLM output)."""
    result = llm.structured_call(ChangeList, prompts.EXTRACT_CHANGES, state["vbpl_text"])
    # Each change costs several LLM calls downstream; cap them for the skeleton.
    changes = result.changes[: get_settings().max_changes]
    return {"changes": [change.model_dump() for change in changes]}
