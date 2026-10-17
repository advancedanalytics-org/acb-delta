from agent.state import ImpactState


def draft_amendment(state: ImpactState) -> ImpactState:
    """Draft the suggested replacement text for each impact.

    Owner: TAI-01. Expected output: {"amendments": [{"chunk_id", "original", "suggested"}, ...]}.
    """
    return {"amendments": []}
