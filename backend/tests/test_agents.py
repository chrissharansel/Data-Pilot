"""Exercises the real LangGraph graph with a scripted fake LLM, so no Ollama is needed."""
import json

import pandas as pd
import pytest
from langchain_core.messages import AIMessage

from app.agents import nodes
from app.agents.graph import build_graph
from app.agents.tools import make_tools


class FakeLLM:
    """Returns pre-written replies in order; accepts bind_tools like ChatOllama."""
    def __init__(self, script):
        self.script = list(script)
        self.calls = []   # every message list the model was shown, for leak checks

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls.append("\n".join(str(getattr(m, "content", m)) for m in messages))
        return self.script.pop(0)


@pytest.fixture
def datasets(tmp_path):
    path = tmp_path / "orders.csv"
    pd.DataFrame({"region": ["N", "N", "S", "S", "S"], "amount": [100, 200, 50, 60, 5000],
                  "note": ["ok", None, "late", "ok", "bulk"]}).to_csv(path, index=False)
    return [{"filename": "orders.csv", "path": str(path),
             "sheets": [{"name": "data", "rows": 5, "columns": ["region", "amount", "note"]}]}]


def tool(datasets, name):
    return next(t for t in make_tools(datasets) if t.name == name)


def test_aggregate_group_by(datasets):
    r = json.loads(tool(datasets, "aggregate").invoke({"dataset": "orders.csv", "column": "amount", "agg": "sum", "group_by": "region"}))
    assert r["result"] == {"S": 5110, "N": 300}


def test_filter_and_missing(datasets):
    r = json.loads(tool(datasets, "filter_rows").invoke({"dataset": "ORDERS", "column": "amount", "operator": ">", "value": "100"}))
    assert r["matching_rows"] == 2
    m = json.loads(tool(datasets, "missing_values").invoke({"dataset": "orders.csv"}))
    assert m["missing"]["note"]["count"] == 1


def test_unknown_column_gives_helpful_error(datasets):
    with pytest.raises(ValueError, match="Columns"):
        tool(datasets, "aggregate").invoke({"dataset": "orders.csv", "column": "nope", "agg": "sum"})


def test_planner_falls_back_on_garbage(monkeypatch, datasets):
    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: FakeLLM([AIMessage(content="not json")]))
    out = nodes.planner_node({"question": "total?", "datasets": datasets, "documents": []})
    assert out["plan"]["steps"] == [{"agent": "data", "task": "total?"}]


def test_planner_drops_data_step_without_datasets(monkeypatch):
    plan = {"objective": "x", "steps": [{"agent": "data", "task": "a"}, {"agent": "rag", "task": "b"}]}
    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: FakeLLM([AIMessage(content=json.dumps(plan))]))
    out = nodes.planner_node({"question": "q", "datasets": [], "documents": [{"filename": "p.pdf"}]})
    assert [s["agent"] for s in out["plan"]["steps"]] == ["rag"]


def test_full_graph_data_and_rag(monkeypatch, datasets):
    plan = {"objective": "Sales by region", "steps": [{"agent": "data", "task": "sum amount by region"},
                                                       {"agent": "rag", "task": "refund policy"}]}
    fake = FakeLLM([
        AIMessage(content=json.dumps(plan)),
        AIMessage(content="", tool_calls=[{"name": "aggregate", "id": "1", "args": {"dataset": "orders.csv", "column": "amount", "agg": "sum", "group_by": "region"}}]),
        AIMessage(content="South totals 5110, North 300."),
        AIMessage(content="South leads with 5110 [D1]. Policy needs approval over 500 [1]."),
        AIMessage(content=json.dumps({"claims": [{"claim": "ok", "verdict": "supported", "evidence": [], "note": "matches"}]})),
    ])
    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: fake)
    monkeypatch.setattr(nodes, "retrieve", lambda q, ids, k=None: [
        {"n": 1, "file_id": "f", "filename": "policy.pdf", "location": "page 2", "snippet": "Orders over 500 need approval.", "score": 0.3}])

    state = {"question": "Which region sells most?", "history": [], "file_ids": None,
             "datasets": datasets, "documents": [{"filename": "policy.pdf"}], "logs": []}
    result = build_graph().invoke(state)
    agents = [l["agent"] for l in result["logs"]]
    assert agents[0] == "planner" and agents[-1] == "verifier" and "writer" in agents
    assert result["verification"]["status"] == "verified"
    assert agents.index("data") < agents.index("rag")  # data agent runs before rag agent
    assert result["evidence"][0]["id"] == "D1"
    assert result["charts"] and result["charts"][0]["figure"]["data"][0]["type"] == "bar"  # grouped aggregate -> bar chart
    assert result["evidence"][0]["tool"] == "aggregate"
    assert "[D1]" in result["answer"] and "[1]" in result["answer"]
    assert not fake.script  # every scripted reply was consumed


def test_rag_only_plan_skips_data_agent(monkeypatch):
    plan = {"objective": "o", "steps": [{"agent": "rag", "task": "t"}]}
    fake = FakeLLM([AIMessage(content=json.dumps(plan)), AIMessage(content="Answer [1]."),
                    AIMessage(content=json.dumps({"claims": [{"claim": "ok", "verdict": "supported", "evidence": [], "note": "matches"}]})),])
    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: fake)
    monkeypatch.setattr(nodes, "retrieve", lambda q, ids, k=None: [
        {"n": 1, "file_id": "f", "filename": "a.pdf", "location": "page 1", "snippet": "text", "score": 0.2}])
    state = {"question": "q", "history": [], "file_ids": None, "datasets": [], "documents": [{"filename": "a.pdf"}], "logs": []}
    result = build_graph().invoke(state)
    assert result["answer"] == "Answer [1]."
    assert [l["agent"] for l in result["logs"]] == ["planner", "rag", "rag", "approval", "writer", "verifier", "verifier"]
