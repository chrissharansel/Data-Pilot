"""LangGraph wiring. The planner picks which agents run; they always execute in this order:
    recall -> planner -> data_agent -> investigation_agent -> rag_agent -> approval_gate -> synthesizer -> verifier
any agent the plan did not ask for is skipped, and a failed verification loops back to the writer once.
The Report Agent runs on demand from a saved investigation (agents/report.py)."""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .nodes import (AGENTS, approval_gate_node, data_agent_node, investigation_agent_node, planner_node,
                    rag_agent_node, recall_node, synthesizer_node, verifier_node)
from .state import InvestigationState

NODE = {"data": "data_agent", "investigate": "investigation_agent", "rag": "rag_agent"}


def next_after(current: str | None):
    """Router: the next planned agent after `current`, or the approval gate if none are left."""
    def route(state: InvestigationState) -> str:
        planned = {s["agent"] for s in state.get("plan", {}).get("steps", [])}
        start = AGENTS.index(current) + 1 if current else 0
        return next((NODE[a] for a in AGENTS[start:] if a in planned), "approval_gate")
    return route


def build_graph(checkpointer=None):
    g = StateGraph(InvestigationState)
    g.add_node("recall", recall_node)
    g.add_node("planner", planner_node)
    g.add_node("data_agent", data_agent_node)
    g.add_node("investigation_agent", investigation_agent_node)
    g.add_node("rag_agent", rag_agent_node)
    g.add_node("approval_gate", approval_gate_node)
    g.add_node("synthesizer", synthesizer_node)
    g.add_node("verifier", verifier_node)
    g.add_edge(START, "recall")
    g.add_edge("recall", "planner")
    targets = [*NODE.values(), "approval_gate"]
    g.add_conditional_edges("planner", next_after(None), targets)
    g.add_conditional_edges("data_agent", next_after("data"), targets)
    g.add_conditional_edges("investigation_agent", next_after("investigate"), targets)
    g.add_conditional_edges("rag_agent", next_after("rag"), targets)
    g.add_edge("approval_gate", "synthesizer")
    g.add_edge("synthesizer", "verifier")
    # if verification fails and a revision is allowed, the verifier sets revision_notes and the writer tries again
    g.add_conditional_edges("verifier", lambda s: "synthesizer" if s.get("revision_notes") else END, ["synthesizer", END])
    return g.compile(checkpointer=checkpointer)


# MemorySaver lets a run pause at the approval gate and resume later (in-process: pending approvals do not survive a restart)
checkpointer = MemorySaver()
graph = build_graph(checkpointer)
