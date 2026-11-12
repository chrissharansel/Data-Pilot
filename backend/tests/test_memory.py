import json
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from app.agents import memory, nodes
from app.agents.graph import build_graph
from app.services import dashboard

from .test_agents import FakeLLM


def hit(files, score, q="Which region leads?", summary="South leads."):
    doc = SimpleNamespace(metadata={"memory_id": "m1", "question": q, "summary": summary, "files": files})
    return (doc, score)


def test_build_strips_citations_and_records_files():
    m = memory.build("Which region leads?", "South leads with 5110 [D1].  Policy [2].", ["b.csv", "a.csv", "a.csv"], "verified", "s1")
    assert m["doc"]["summary"] == "South leads with 5110 . Policy ." and m["doc"]["files"] == ["a.csv", "b.csv"]
    assert m["meta"]["files"] == "a.csv|b.csv" and m["text"].startswith("Which region leads?")


def test_recall_filters_by_distance_and_files(monkeypatch):
    monkeypatch.setattr(memory.vectorstore, "search_memory", lambda q, k: [hit("a.csv", 0.5), hit("a.csv", 1.6), hit("other.csv", 0.4), hit("", 0.6)])
    out = memory.recall("q", ["a.csv"])
    assert [m["score"] for m in out] == [0.5, 0.6]       # too distant and wrong-file memories dropped; file-less memory kept


def test_recall_survives_store_errors(monkeypatch):
    def boom(q, k):
        raise RuntimeError("chroma down")
    monkeypatch.setattr(memory.vectorstore, "search_memory", boom)
    assert memory.recall("q", ["a.csv"]) == []


def test_graph_passes_memory_as_context_not_evidence(monkeypatch):
    mem = [{"id": "m1", "question": "Earlier question", "summary": "Earlier finding 4242.", "files": [], "score": 0.3}]
    monkeypatch.setattr(nodes, "recall_memories", lambda q, names, k=None: mem)
    plan = {"objective": "o", "steps": [{"agent": "rag", "task": "t"}]}
    fake = FakeLLM([AIMessage(content=json.dumps(plan)), AIMessage(content="Answer [1]."),
                    AIMessage(content=json.dumps({"claims": [{"claim": "Answer", "verdict": "supported", "evidence": ["1"], "note": ""}]}))])
    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: fake)
    monkeypatch.setattr(nodes, "retrieve", lambda q, ids, k=None: [{"n": 1, "file_id": "f", "filename": "a.pdf", "location": "p1", "snippet": "text", "score": 0.2}])
    result = build_graph().invoke({"question": "q", "history": [], "file_ids": None, "use_memory": True, "datasets": [],
                                   "documents": [{"filename": "a.pdf"}], "logs": [], "evidence": [], "charts": []})
    assert "Earlier finding 4242" in fake.calls[0] and "NOT evidence" in fake.calls[1]    # planner and writer both see it, labelled
    assert any(l["agent"] == "memory" for l in result["logs"])


def test_memory_off_skips_recall(monkeypatch):
    monkeypatch.setattr(nodes, "recall_memories", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")))
    assert nodes.recall_node({"question": "q", "use_memory": False}) == {"memories": [], "logs": []}


def test_a_memory_number_cannot_ground_an_answer():
    from app.agents import verify
    det = verify.check_answer("The total is 4242 [D1].", "q", [{"id": "D1", "tool": "aggregate", "args": {}, "result": '{"result": 10}'}], [])
    assert det["ungrounded"] == ["4242"]       # numbers only count if they are in this run's evidence


def test_dashboard_helpers():
    files = [{"_id": "1", "filename": "a.csv", "kind": "tabular", "profile": {"sheets": [{"rows": 10, "columns": [{"nulls": 5}, {"nulls": 0}]}]}},
             {"_id": "2", "filename": "p.pdf", "kind": "document"}]
    ov = dashboard.datasets_overview(files)
    assert ov == [{"id": "1", "filename": "a.csv", "sheets": 1, "rows": 10, "columns": 2, "missing_pct": 25.0}]
    msgs = [{"id": "m", "question": "q", "charts": [{"id": "C1", "title": "t", "figure": {}}, {"id": "C2", "title": "u", "figure": {}}]}]
    assert [c["title"] for c in dashboard.chart_gallery(msgs, limit=1)] == ["t"]
