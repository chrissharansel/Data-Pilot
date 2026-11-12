"""Runs the real graph with a checkpointer so the approval gate can pause (interrupt) and resume."""
import asyncio
import json

import pandas as pd
import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Command

from app.agents import nodes
from app.agents.graph import build_graph
from app.agents.state import append_or_replace, REPLACE
from app.config import settings
from langgraph.checkpoint.memory import MemorySaver

from .test_agents import FakeLLM

EMAIL = "alice@example.com"


@pytest.fixture
def people(tmp_path):
    path = tmp_path / "people.csv"
    pd.DataFrame({"name": ["A", "B", "C"], "customer_email": [EMAIL, "bob@example.com", "cy@example.com"], "amount": [10, 20, 30]}).to_csv(path, index=False)
    return [{"filename": "people.csv", "path": str(path), "sheets": [{"name": "data", "rows": 3, "columns": ["name", "customer_email", "amount"]}]}]


def script():
    plan = {"objective": "list orders", "steps": [{"agent": "data", "task": "find rows with an email"}]}
    return [
        AIMessage(content=json.dumps(plan)),
        AIMessage(content="", tool_calls=[{"name": "filter_rows", "id": "1", "args": {"dataset": "people.csv", "column": "customer_email", "operator": "contains", "value": "@"}}]),
        AIMessage(content=f"Found 3 rows, first is {EMAIL}."),   # Data Agent summary written from RAW values
        AIMessage(content="Three customers have an email on file [D1]."),
        AIMessage(content=json.dumps({"claims": [{"claim": "Three customers", "verdict": "supported", "evidence": ["D1"], "note": ""}]})),
    ]


async def drive(graph, first_input, cfg):
    """Mimics the router: collect streamed updates until the run ends or pauses."""
    seen = {}
    async for update in graph.astream(first_input, cfg, stream_mode="updates"):
        for node, out in update.items():
            seen[node] = out
    return seen


def initial(people):
    return {"question": "show customers with email", "history": [], "file_ids": None, "use_memory": False,
            "datasets": people, "documents": [], "logs": [], "evidence": [], "charts": []}


def run(monkeypatch, people, decision):
    fake = FakeLLM(script())
    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: fake)
    graph = build_graph(MemorySaver())
    cfg = {"configurable": {"thread_id": "t"}}
    first = asyncio.run(drive(graph, initial(people), cfg))
    resumed = asyncio.run(drive(graph, Command(resume={"decision": decision}), cfg)) if decision else None
    return fake, first, resumed


def test_run_pauses_at_gate_with_findings_but_no_raw_values(monkeypatch, people):
    fake, first, resumed = run(monkeypatch, people, None)
    payload = first["__interrupt__"][0].value
    assert payload["type"] == "sensitive_data"
    assert payload["findings"][0]["columns"] == ["customer_email"]
    assert EMAIL not in json.dumps(payload)                      # the approval card never shows the raw values
    assert "synthesizer" not in first                             # the writer has not run yet
    logs = " ".join(l["detail"] for l in first["data_agent"]["logs"])
    assert EMAIL not in logs                                      # streamed logs are masked before any decision


def test_mask_decision_hides_values_from_the_writer(monkeypatch, people):
    fake, first, resumed = run(monkeypatch, people, "mask")
    writer_prompt = fake.calls[3]                                 # planner, data x2, writer
    assert EMAIL not in writer_prompt and "[REDACTED" in writer_prompt
    assert "Found 3 rows" not in writer_prompt                    # raw-value agent summary was withheld
    assert resumed["approval_gate"]["approval"]["decision"] == "mask"
    assert resumed["verifier"]["verification"]["status"] == "verified"
    assert not fake.script


def test_approve_decision_keeps_values(monkeypatch, people):
    fake, first, resumed = run(monkeypatch, people, "approve")
    assert EMAIL in fake.calls[3]
    assert resumed["approval_gate"]["approval"]["decided_by"] == "human"


def test_reject_decision_removes_the_evidence(monkeypatch, people):
    plan = {"objective": "o", "steps": [{"agent": "data", "task": "t"}]}
    fake = FakeLLM([AIMessage(content=json.dumps(plan)),
                    AIMessage(content="", tool_calls=[{"name": "filter_rows", "id": "1", "args": {"dataset": "people.csv", "column": "customer_email", "operator": "contains", "value": "@"}}]),
                    AIMessage(content="x")])
    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: fake)
    graph = build_graph(MemorySaver())
    cfg = {"configurable": {"thread_id": "t"}}
    asyncio.run(drive(graph, initial(people), cfg))
    resumed = asyncio.run(drive(graph, Command(resume={"decision": "reject"}), cfg))
    assert "couldn't find evidence" in resumed["synthesizer"]["answer"]   # nothing left to write from


def test_policy_mask_never_pauses(monkeypatch, people):
    monkeypatch.setattr(settings, "sensitive_policy", "mask")
    fake = FakeLLM(script())
    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: fake)
    result = build_graph().invoke(initial(people))               # no checkpointer: an interrupt would raise
    assert result["approval"]["decided_by"] == "policy" and EMAIL not in fake.calls[3]


def test_policy_allow_disables_gate(monkeypatch, people):
    monkeypatch.setattr(settings, "sensitive_policy", "allow")
    fake = FakeLLM(script())
    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: fake)
    result = build_graph().invoke(initial(people))
    assert result["approval"]["policy"] == "allow" and EMAIL in fake.calls[3]


def test_replace_reducer():
    assert append_or_replace([{"a": 1}], [{"b": 2}]) == [{"a": 1}, {"b": 2}]
    assert append_or_replace([{"a": 1}], [REPLACE, {"c": 3}]) == [{"c": 3}]
    assert append_or_replace([{"a": 1}], [REPLACE]) == []
