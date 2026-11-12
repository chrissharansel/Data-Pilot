import operator
from typing import Annotated, TypedDict


REPLACE = {"__replace__": True}


def append_or_replace(left: list, right: list) -> list:
    """Reducer: nodes normally append; a node can overwrite the list by returning [REPLACE, *new_items].
    The approval gate uses this to swap raw evidence for masked evidence."""
    if right and isinstance(right[0], dict) and right[0].get("__replace__"):
        return list(right[1:])
    return (left or []) + (right or [])


class InvestigationState(TypedDict, total=False):
    # inputs (set by the router)
    question: str
    history: list[dict]
    file_ids: list[str] | None
    use_memory: bool
    datasets: list[dict]        # tabular files: {filename, path, sheets:[{name, rows, columns}]}
    documents: list[dict]       # text files: {filename}
    # produced by agents
    plan: dict                  # {objective, steps:[{agent, task}]}
    data_findings: str
    investigation_findings: str
    sources: list[dict]         # RAG passages
    answer: str
    memories: list[dict]        # related past findings: context only, never evidence
    approval: dict              # outcome of the sensitive-data gate
    verification: dict          # Verification Agent result
    revision_notes: str         # feedback for the Writer when verification fails
    revisions: int
    # shared, appended to by several agents (the reducer concatenates instead of overwriting)
    evidence: Annotated[list[dict], append_or_replace]   # every tool call: {id, tool, args, result}; ids D1.. / I1..
    charts: Annotated[list[dict], append_or_replace]     # Plotly figures: {id, title, figure}
    logs: Annotated[list[dict], operator.add]       # execution log
