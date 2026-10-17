from agent.state import ImpactState


def judge_impact(state: ImpactState) -> ImpactState:
    """Decide whether each candidate is affected: type, severity, reasoning, citation.

    Owner: TAI-01. Expected output: {"impacts": [{"chunk_id", "type", "severity",
    "reasoning", "citation"}, ...]}.
    """
    return {"impacts": []}
