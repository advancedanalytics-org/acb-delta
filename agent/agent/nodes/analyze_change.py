from agent.nodes.draft_amendment import draft_amendment
from agent.nodes.judge_impact import judge_impact
from agent.nodes.retrieve import retrieve
from agent.schemas import Change, ImpactOut
from agent.state import ChangeState, ImpactState


def analyze_change(state: ChangeState) -> ImpactState:
    """One fan-out branch: retrieve candidates for a change, judge each, draft the affected."""
    change = Change.model_validate(state["change"])
    vbpl_title = next(
        (line.strip() for line in state["vbpl_text"].splitlines() if line.strip()), ""
    )
    impacts = []
    for candidate in retrieve(change):
        judgement = judge_impact(change, candidate, vbpl_title)
        if not judgement.affected:
            continue
        amendment = draft_amendment(change, candidate, judgement)
        impact = ImpactOut(
            chunk_id=candidate.chunk_id,
            doc_id=candidate.doc_id,
            location=candidate.location,
            page=candidate.page,
            bboxes=candidate.bboxes,
            affected_text=candidate.text,
            change_clause=change.text,
            type=judgement.type,
            severity=judgement.severity,
            reasoning=judgement.reasoning,
            citation=judgement.citation,
            suggested_text=amendment.suggested_text,
        )
        impacts.append(impact.model_dump())
    return {"impacts": impacts}
