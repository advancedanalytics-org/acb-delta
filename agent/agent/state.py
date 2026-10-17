"""Graph state shared by every node. Nodes return partial updates of this dict."""

import operator
from typing import Annotated, TypedDict


class ImpactState(TypedDict, total=False):
    vbpl_text: str
    # Clauses added / amended / repealed by the new VBPL (extract_changes), as `Change` dicts.
    changes: list[dict]
    # `ImpactOut` dicts. Parallel analyze_change branches each append theirs; the reducer merges.
    impacts: Annotated[list[dict], operator.add]


class ChangeState(TypedDict):
    """Payload `Send` gives one analyze_change branch."""

    change: dict
    vbpl_text: str
