"""Graph state shared by every node. Nodes return partial updates of this dict."""

from typing import TypedDict


class ImpactState(TypedDict, total=False):
    vbpl_text: str
    # Clauses added / amended / repealed by the new VBPL (extract_changes).
    changes: list[dict]
    # Internal-document chunks retrieved for each change (retrieve).
    candidates: list[dict]
    # Confirmed impacts: type, severity, reasoning, citation (judge_impact).
    impacts: list[dict]
    # Original → suggested text per impact (draft_amendment).
    amendments: list[dict]
