from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import document_service

router = APIRouter(prefix="/api/projects/{project_id}/documents", tags=["documents"])


class DocCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = ""
    filename: str | None = None
    tags: list[str] = []


class DocUpdate(BaseModel):
    title: str | None = None
    content: str | None = None


class DocGenerate(BaseModel):
    query: str = Field(..., min_length=3)
    title: str | None = None


@router.get("")
async def list_documents(project_id: str):
    return await document_service.list_documents(project_id)


@router.post("")
async def create_document(project_id: str, body: DocCreate):
    return await document_service.create_document(
        project_id,
        title=body.title,
        content=body.content,
        filename=body.filename,
        source="manual",
        tags=body.tags,
    )


@router.post("/generate")
async def generate_document(project_id: str, body: DocGenerate):
    try:
        return await document_service.generate_document(project_id, body.query, body.title)
    except Exception as e:
        raise HTTPException(500, f"Generation failed: {e}") from e


@router.get("/{doc_id}")
async def get_document(project_id: str, doc_id: str):
    doc = await document_service.get_document(project_id, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@router.put("/{doc_id}")
async def update_document(project_id: str, doc_id: str, body: DocUpdate):
    doc = await document_service.update_document(
        project_id, doc_id, title=body.title, content=body.content
    )
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@router.delete("/{doc_id}")
async def delete_document(project_id: str, doc_id: str):
    ok = await document_service.delete_document(project_id, doc_id)
    if not ok:
        raise HTTPException(404, "Document not found")
    return {"ok": True}
