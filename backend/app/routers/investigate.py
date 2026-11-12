"""Runs the agent graph and streams each agent action to the browser as Server-Sent Events.
If the approval gate pauses the run, the stream ends with an `approval` event; POST /resume continues it."""
import json
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel

from .. import db
from ..agents import memory
from ..agents.graph import checkpointer, graph
from ..agents.state import REPLACE
from ..services import vectorstore

router = APIRouter(prefix="/api/investigate", tags=["investigate"])

PENDING: dict[str, dict] = {}   # thread_id -> run context waiting for a human decision (in-process)
REMEMBER = {"verified", "partially_verified"}


class InvestigateRequest(BaseModel):
    question: str
    session_id: str | None = None
    file_ids: list[str] | None = None
    use_memory: bool = True


class ResumeRequest(BaseModel):
    thread_id: str
    decision: Literal["approve", "mask", "reject"]


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _accumulate(final: dict, out: dict):
    """Node updates arrive one at a time. Lists accumulate; [REPLACE, ...] overwrites (used by the approval gate)."""
    for k, v in out.items():
        if k == "logs":
            continue
        if k in ("evidence", "charts"):
            if v and isinstance(v[0], dict) and v[0].get("__replace__"):
                final[k] = list(v[1:])
            else:
                final.setdefault(k, []).extend(v)
        else:
            final[k] = v


async def _run(graph_input, thread_id: str, ctx: dict):
    config = {"configurable": {"thread_id": thread_id}}
    final, logs = ctx["final"], ctx["logs"]
    try:
        async for update in graph.astream(graph_input, config, stream_mode="updates"):
            for node, out in update.items():
                if node == "__interrupt__":
                    PENDING[thread_id] = ctx
                    yield sse("approval", {"thread_id": thread_id, **out[0].value})
                    return
                out = out or {}
                for entry in out.get("logs", []):
                    logs.append(entry)
                    yield sse("log", entry)
                if node == "planner":
                    yield sse("plan", out["plan"])
                _accumulate(final, out)
    except Exception as e:
        PENDING.pop(thread_id, None)
        yield sse("error", {"message": f"The investigation failed. Check that Ollama is running and qwen3:4b is pulled. ({e})"})
        return

    result = {"id": uuid.uuid4().hex, "answer": final.get("answer", ""), "sources": final.get("sources", []),
              "verification": final.get("verification"), "approval": final.get("approval"),
              "evidence": final.get("evidence", []), "charts": final.get("charts", []), "plan": final.get("plan"), "logs": logs}
    await db.messages.insert_one({"session_id": ctx["session_id"], "role": "assistant", "content": result["answer"],
                                  "question": ctx["question"], **{k: v for k, v in result.items() if k != "answer"}, "ts": _now()})
    PENDING.pop(thread_id, None)
    if hasattr(checkpointer, "delete_thread"):
        checkpointer.delete_thread(thread_id)
    await _remember(ctx, result)
    yield sse("final", result)


async def _remember(ctx: dict, result: dict):
    """Only verified findings are remembered, and never when sensitive data was involved."""
    v, a = result.get("verification") or {}, result.get("approval") or {}
    if not ctx["use_memory"] or v.get("status") not in REMEMBER or a.get("flagged"):
        return
    try:
        m = memory.build(ctx["question"], result["answer"], ctx["files"], v["status"], ctx["session_id"])
        await run_in_threadpool(vectorstore.add_memory, m["id"], m["text"], m["meta"])
        await db.memories.insert_one(m["doc"])
    except Exception:
        pass  # memory is a convenience; never fail the investigation because of it


def _stream(gen):
    return StreamingResponse(gen, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/stream")
async def investigate(req: InvestigateRequest):
    if not req.question.strip():
        raise HTTPException(400, "Question is empty")
    session_id = req.session_id or uuid.uuid4().hex

    query = {"_id": {"$in": req.file_ids}} if req.file_ids else {}
    datasets, documents = [], []
    async for f in db.files.find(query):
        if f["kind"] == "tabular":
            datasets.append({"filename": f["filename"], "path": f["path"],
                             "sheets": [{"name": s["sheet"], "rows": s["rows"], "columns": [c["name"] for c in s["columns"]]}
                                        for s in f["profile"]["sheets"]]})
        else:
            documents.append({"filename": f["filename"]})

    history = [m async for m in db.messages.find({"session_id": session_id}, {"_id": 0}).sort("ts", 1)]
    await db.messages.insert_one({"session_id": session_id, "role": "user", "content": req.question, "ts": _now()})
    state = {"question": req.question, "history": history, "file_ids": req.file_ids, "use_memory": req.use_memory,
             "datasets": datasets, "documents": documents, "logs": [], "evidence": [], "charts": []}
    thread_id = uuid.uuid4().hex
    ctx = {"session_id": session_id, "question": req.question, "use_memory": req.use_memory, "logs": [], "final": {},
           "files": [d["filename"] for d in datasets] + [d["filename"] for d in documents]}

    async def events():
        yield sse("session", {"session_id": session_id})
        async for chunk in _run(state, thread_id, ctx):
            yield chunk
    return _stream(events())


@router.post("/resume")
async def resume(req: ResumeRequest):
    ctx = PENDING.pop(req.thread_id, None)
    if not ctx:
        raise HTTPException(404, "This approval request is no longer available (the server may have restarted). Please ask the question again.")

    async def events():
        yield sse("session", {"session_id": ctx["session_id"]})
        async for chunk in _run(Command(resume={"decision": req.decision}), req.thread_id, ctx):
            yield chunk
    return _stream(events())
