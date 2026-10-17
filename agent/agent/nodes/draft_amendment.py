from agent import llm, prompts
from agent.schemas import Amendment, Candidate, Change, ImpactJudgement


def draft_amendment(change: Change, candidate: Candidate, judgement: ImpactJudgement) -> Amendment:
    """Draft the suggested replacement text for one affected passage."""
    user = "\n\n".join(
        [
            prompts.change_block(change.clause, change.kind, change.text),
            prompts.passage_block(candidate.doc_id, candidate.location, candidate.text),
            f"Lý do phải sửa: {judgement.reasoning}",
        ]
    )
    return llm.structured_call(Amendment, prompts.DRAFT_AMENDMENT, user)
