import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import db
from ..rag import pipeline

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None
    file_ids: list[str] | None = None


def _now():
    return datetime.now(timezone.utc).isoformat()


@router.post("")
async def chat(req: ChatRequest):
    if not req.question.strip():
        raise HTTPException(400, "Question is empty")
    session_id = req.session_id or uuid.uuid4().hex
    history = [m async for m in db.messages.find({"session_id": session_id}, {"_id": 0}).sort("ts", 1)]
    await db.messages.insert_one({"session_id": session_id, "role": "user", "content": req.question, "ts": _now()})
    try:
        result = await run_in_threadpool(pipeline.answer, req.question, req.file_ids, history)
    except Exception as e:
        raise HTTPException(502, f"The model request failed. Check that Ollama is running and qwen3:4b is pulled. ({e})")
    await db.messages.insert_one({"session_id": session_id, "role": "assistant", "content": result["answer"],
                                  "sources": result["sources"], "ts": _now()})
    return {"session_id": session_id, **result}


@router.get("/sessions")
async def sessions():
    stages = [{"$sort": {"ts": 1}},
              {"$group": {"_id": "$session_id", "title": {"$first": "$content"}, "updated": {"$last": "$ts"}, "count": {"$sum": 1}}},
              {"$sort": {"updated": -1}}, {"$limit": 30}]
    cursor = await db.messages.aggregate(stages)
    return [{"session_id": d["_id"], "title": d["title"][:80], "updated": d["updated"], "count": d["count"]} async for d in cursor]


@router.get("/{session_id}")
async def history(session_id: str):
    return [m async for m in db.messages.find({"session_id": session_id}, {"_id": 0}).sort("ts", 1)]
