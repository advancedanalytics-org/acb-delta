from agent import llm, prompts
from agent.schemas import Candidate, Change, ImpactJudgement


def judge_impact(change: Change, candidate: Candidate, vbpl_title: str) -> ImpactJudgement:
    """Decide whether a candidate is affected by a change: type, severity, reasoning, citation."""
    user = "\n\n".join(
        [
            f"VBPL mới: {vbpl_title}",
            prompts.change_block(change.clause, change.kind, change.text),
            prompts.passage_block(candidate.doc_id, candidate.location, candidate.text),
        ]
    )
    return llm.structured_call(ImpactJudgement, prompts.JUDGE_IMPACT, user)
