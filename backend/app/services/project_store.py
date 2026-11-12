"""Project CRUD helpers."""
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from .. import db


def _oid(id_str: str) -> ObjectId:
    return ObjectId(id_str)


def serialize(doc: dict) -> dict:
    if not doc:
        return doc
    out = {**doc}
    out["id"] = str(out.pop("_id"))
    for k, v in list(out.items()):
        if isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
    return out


async def create_project(name: str, description: str = "") -> dict:
    now = datetime.now(timezone.utc)
    doc = {
        "name": name.strip(),
        "description": (description or "").strip(),
        "default_branch": "main",
        "created_at": now,
        "updated_at": now,
    }
    res = await db.projects.insert_one(doc)
    doc["_id"] = res.inserted_id
    # Create default branch
    await db.code_branches.insert_one({
        "project_id": res.inserted_id,
        "name": "main",
        "head_commit_id": None,
        "is_default": True,
        "created_at": now,
    })
    return serialize(doc)


async def list_projects() -> list[dict]:
    cursor = db.projects.find().sort("updated_at", -1)
    return [serialize(d) async for d in cursor]


async def get_project(project_id: str) -> dict | None:
    doc = await db.projects.find_one({"_id": _oid(project_id)})
    return serialize(doc) if doc else None


async def update_project(project_id: str, **fields: Any) -> dict | None:
    allowed = {"name", "description", "default_branch"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return await get_project(project_id)
    updates["updated_at"] = datetime.now(timezone.utc)
    await db.projects.update_one({"_id": _oid(project_id)}, {"$set": updates})
    return await get_project(project_id)


async def delete_project(project_id: str) -> bool:
    oid = _oid(project_id)
    res = await db.projects.delete_one({"_id": oid})
    if res.deleted_count:
        await db.documents.delete_many({"project_id": oid})
        await db.code_branches.delete_many({"project_id": oid})
        await db.code_commits.delete_many({"project_id": oid})
    return res.deleted_count > 0
