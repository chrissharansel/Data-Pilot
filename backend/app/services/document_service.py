"""Project document management + AI generation."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bson import ObjectId

from .. import db
from ..config import settings
from .llm import chat as llm_chat


def _project_docs_dir(project_id: str) -> Path:
    p = Path(settings.projects_dir) / project_id / "documents"
    p.mkdir(parents=True, exist_ok=True)
    return p


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


async def list_documents(project_id: str) -> list[dict]:
    cursor = db.documents.find({"project_id": ObjectId(project_id)}).sort("updated_at", -1)
    return [serialize(d) async for d in cursor]


async def get_document(project_id: str, doc_id: str) -> dict | None:
    doc = await db.documents.find_one({
        "_id": ObjectId(doc_id),
        "project_id": ObjectId(project_id),
    })
    if not doc:
        return None
    path = Path(doc.get("path", ""))
    if path.exists() and doc.get("content_type", "").startswith("text"):
        try:
            doc["content"] = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            doc["content"] = ""
    return serialize(doc)


async def create_document(
    project_id: str,
    title: str,
    content: str = "",
    filename: Optional[str] = None,
    source: str = "manual",
    tags: list[str] | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    safe_name = (filename or f"{title.replace(' ', '_').lower()}.md").replace("..", "")
    docs_dir = _project_docs_dir(project_id)
    file_path = docs_dir / safe_name
    file_path.write_text(content or "", encoding="utf-8")

    doc = {
        "project_id": ObjectId(project_id),
        "title": title.strip(),
        "filename": safe_name,
        "content_type": "text/markdown",
        "path": str(file_path),
        "source": source,
        "created_at": now,
        "updated_at": now,
        "created_by": "ai" if source == "ai_generated" else "user",
        "tags": tags or [],
        "chroma_ids": [],
    }
    res = await db.documents.insert_one(doc)
    doc["_id"] = res.inserted_id
    out = serialize(doc)
    out["content"] = content or ""
    return out


async def update_document(project_id: str, doc_id: str, title: str | None = None, content: str | None = None) -> dict | None:
    existing = await db.documents.find_one({"_id": ObjectId(doc_id), "project_id": ObjectId(project_id)})
    if not existing:
        return None
    updates: dict = {"updated_at": datetime.now(timezone.utc)}
    if title is not None:
        updates["title"] = title.strip()
    if content is not None:
        path = Path(existing["path"])
        path.write_text(content, encoding="utf-8")
    await db.documents.update_one({"_id": ObjectId(doc_id)}, {"$set": updates})
    return await get_document(project_id, doc_id)


async def delete_document(project_id: str, doc_id: str) -> bool:
    existing = await db.documents.find_one({"_id": ObjectId(doc_id), "project_id": ObjectId(project_id)})
    if not existing:
        return False
    path = Path(existing.get("path", ""))
    if path.exists():
        path.unlink(missing_ok=True)
    res = await db.documents.delete_one({"_id": ObjectId(doc_id)})
    return res.deleted_count > 0


async def generate_document(project_id: str, query: str, title: str | None = None) -> dict:
    """Use local LLM to write a markdown document from a natural-language request."""
    prompt = f"""You are a technical writer. Write a clear, well-structured Markdown document based on this request.

Request:
{query}

Rules:
- Output ONLY the markdown content. No preamble.
- Use headings, bullet lists and short paragraphs.
- Be concrete and professional.
"""
    content = await llm_chat([{"role": "user", "content": prompt}])
    if "</think>" in content:
        content = content.split("</think>", 1)[-1].strip()
    doc_title = title or query[:80].strip() or "Generated Document"
    return await create_document(
        project_id=project_id,
        title=doc_title,
        content=content,
        filename=f"{doc_title.replace(' ', '_').lower()[:60]}.md",
        source="ai_generated",
        tags=["ai-generated"],
    )
