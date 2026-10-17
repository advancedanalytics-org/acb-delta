from agent.state import ImpactState


def extract_changes(state: ImpactState) -> ImpactState:
    """Split the VBPL into new / amended / repealed clauses (structured LLM output).

    Owner: TAI-01. Expected output: {"changes": [{"clause", "kind", "text"}, ...]}.
    """
    return {"changes": []}
