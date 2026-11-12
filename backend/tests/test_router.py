"""End-to-end through the real FastAPI routes: SSE stream -> approval pause -> resume -> final, with a fake MongoDB."""
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app import db
from app.agents import nodes
from app.main import app
from app.routers import investigate as inv

from .test_agents import FakeLLM
from .test_approval import script as sensitive_script

client = TestClient(app)


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def __aiter__(self):
        async def gen():
            for d in self.docs:
                yield d
        return gen()


class FakeCol:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find(self, query=None, proj=None):
        return FakeCursor(list(self.docs))

    async def insert_one(self, doc):
        self.docs.append(doc)


def events(response):
    out = []
    for block in response.text.strip().split("\n\n"):
        name = block.split("\n")[0].removeprefix("event: ")
        out.append((name, json.loads(block.split("\n")[1].removeprefix("data: "))))
    return out


@pytest.fixture
def env(monkeypatch, tmp_path):
    path = tmp_path / "people.csv"
    pd.DataFrame({"name": ["A", "B", "C"], "customer_email": ["alice@example.com", "bob@example.com", "cy@example.com"], "amount": [10, 20, 30]}).to_csv(path, index=False)
    f = {"_id": "f1", "filename": "people.csv", "kind": "tabular", "path": str(path),
         "profile": {"sheets": [{"sheet": "data", "rows": 3, "columns": [{"name": "name"}, {"name": "customer_email"}, {"name": "amount"}]}]}}
    cols = {"files": FakeCol([f]), "messages": FakeCol(), "memories": FakeCol()}
    for k, v in cols.items():
        monkeypatch.setattr(db, k, v)
    remembered = []
    monkeypatch.setattr(inv.vectorstore, "add_memory", lambda mid, text, meta: remembered.append(text))
    inv.PENDING.clear()
    return cols, remembered


def use(monkeypatch, script):
    fake = FakeLLM(script)
    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: fake)
    return fake


def test_sensitive_run_pauses_resumes_and_is_not_remembered(monkeypatch, env):
    cols, remembered = env
    use(monkeypatch, sensitive_script())
    first = events(client.post("/api/investigate/stream", json={"question": "show customers with email"}))
    names = [n for n, _ in first]
    assert names[0] == "session" and names[-1] == "approval" and "final" not in names
    approval = first[-1][1]
    assert approval["findings"][0]["columns"] == ["customer_email"]
    assert "alice@example.com" not in json.dumps(first)                 # nothing raw crossed the wire before the decision
    assert [d for d in cols["messages"].docs if d["role"] == "assistant"] == []   # nothing saved until the run finishes

    second = events(client.post("/api/investigate/resume", json={"thread_id": approval["thread_id"], "decision": "mask"}))
    assert second[-1][0] == "final"
    final = second[-1][1]
    assert final["approval"]["decision"] == "mask" and final["verification"]["status"] == "verified"
    assert "alice@example.com" not in json.dumps(final)
    saved = [d for d in cols["messages"].docs if d["role"] == "assistant"]
    assert len(saved) == 1 and saved[0]["id"] == final["id"] and saved[0]["question"] == "show customers with email"
    assert remembered == []                                             # sensitive runs are never memorised


def test_resume_with_unknown_thread_is_404(env):
    r = client.post("/api/investigate/resume", json={"thread_id": "nope", "decision": "mask"})
    assert r.status_code == 404 and "no longer available" in r.json()["detail"]


def test_resume_rejects_invalid_decision(env):
    assert client.post("/api/investigate/resume", json={"thread_id": "x", "decision": "yolo"}).status_code == 422


def test_clean_run_streams_final_and_is_remembered(monkeypatch, env):
    cols, remembered = env
    plan = {"objective": "o", "steps": [{"agent": "data", "task": "sum"}]}
    use(monkeypatch, [
        AIMessage(content=json.dumps(plan)),
        AIMessage(content="", tool_calls=[{"name": "aggregate", "id": "1", "args": {"dataset": "people.csv", "column": "amount", "agg": "sum"}}]),
        AIMessage(content="Total is 60."),
        AIMessage(content="The total amount is 60 [D1]."),
        AIMessage(content=json.dumps({"claims": [{"claim": "total is 60", "verdict": "supported", "evidence": ["D1"], "note": ""}]})),
    ])
    ev = events(client.post("/api/investigate/stream", json={"question": "total amount?"}))
    names = [n for n, _ in ev]
    assert names[0] == "session" and "plan" in names and names[-1] == "final" and "approval" not in names
    assert ev[-1][1]["approval"] == {"flagged": False}
    assert len(remembered) == 1 and "total amount?" in remembered[0]
    assert len(cols["memories"].docs) == 1 and cols["memories"].docs[0]["status"] == "verified"


def test_use_memory_false_does_not_remember(monkeypatch, env):
    cols, remembered = env
    plan = {"objective": "o", "steps": [{"agent": "data", "task": "sum"}]}
    use(monkeypatch, [AIMessage(content=json.dumps(plan)),
                      AIMessage(content="", tool_calls=[{"name": "aggregate", "id": "1", "args": {"dataset": "people.csv", "column": "amount", "agg": "sum"}}]),
                      AIMessage(content="60"), AIMessage(content="Total is 60 [D1]."),
                      AIMessage(content=json.dumps({"claims": [{"claim": "60", "verdict": "supported", "evidence": ["D1"], "note": ""}]}))])
    client.post("/api/investigate/stream", json={"question": "total?", "use_memory": False})
    assert remembered == [] and cols["memories"].docs == []
