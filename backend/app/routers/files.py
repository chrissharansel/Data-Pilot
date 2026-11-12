import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from .. import db
from ..config import settings
from ..services import vectorstore
from ..services.parsers import SUPPORTED, parse_file

router = APIRouter(prefix="/api/files", tags=["files"])


def _public(doc: dict) -> dict:
    doc["id"] = doc.pop("_id")
    return doc


def _ingest(path: Path, name: str, file_id: str):
    parsed = parse_file(path, name)
    return parsed, vectorstore.add_documents(parsed.documents, file_id)


@router.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    results, errors = [], []
    for f in files:
        ext = Path(f.filename).suffix.lower()
        if ext not in SUPPORTED:
            errors.append({"filename": f.filename, "error": f"Unsupported type {ext or '(none)'}"})
            continue
        file_id = uuid.uuid4().hex
        path = Path(settings.upload_dir) / f"{file_id}{ext}"
        path.write_bytes(await f.read())
        try:
            parsed, chunks = await run_in_threadpool(_ingest, path, f.filename, file_id)
        except Exception as e:  # corrupt file, bad encoding, etc.
            path.unlink(missing_ok=True)
            errors.append({"filename": f.filename, "error": str(e)})
            continue
        doc = {"_id": file_id, "filename": f.filename, "ext": ext, "kind": parsed.kind, "path": str(path),
               "size": path.stat().st_size, "chunks": chunks, "pages": parsed.pages, "profile": parsed.profile,
               "uploaded_at": datetime.now(timezone.utc).isoformat()}
        await db.files.insert_one(doc)
        results.append(_public(doc))
    return {"uploaded": results, "errors": errors}


@router.get("")
async def list_files():
    return [_public(d) async for d in db.files.find({}, {"profile": 0}).sort("uploaded_at", -1)]


@router.get("/{file_id}")
async def get_file(file_id: str):
    doc = await db.files.find_one({"_id": file_id})
    if not doc:
        raise HTTPException(404, "File not found")
    return _public(doc)


@router.delete("/{file_id}")
async def delete_file(file_id: str):
    doc = await db.files.find_one({"_id": file_id})
    if not doc:
        raise HTTPException(404, "File not found")
    await run_in_threadpool(vectorstore.delete_file, file_id)
    Path(doc["path"]).unlink(missing_ok=True)
    await db.files.delete_one({"_id": file_id})
    return {"deleted": file_id}
