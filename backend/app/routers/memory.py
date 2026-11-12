from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from .. import db
from ..services import vectorstore

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("")
async def list_memories():
    out = []
    async for d in db.memories.find({}).sort("created_at", -1).limit(100):
        d["id"] = d.pop("_id")
        out.append(d)
    return out


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str):
    res = await db.memories.delete_one({"_id": memory_id})
    if not res.deleted_count:
        raise HTTPException(404, "Memory not found")
    await run_in_threadpool(vectorstore.delete_memory, [memory_id])
    return {"deleted": memory_id}


@router.delete("")
async def clear_memories():
    ids = [d["_id"] async for d in db.memories.find({}, {"_id": 1})]
    await db.memories.delete_many({})
    await run_in_threadpool(vectorstore.delete_memory, ids)
    return {"deleted": len(ids)}
