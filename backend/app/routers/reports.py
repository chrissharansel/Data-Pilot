import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import db
from ..agents.report import generate_report
from ..services import export

router = APIRouter(prefix="/api/reports", tags=["reports"])


class ReportRequest(BaseModel):
    session_id: str
    message_id: str


def _public(doc: dict) -> dict:
    doc["id"] = doc.pop("_id")
    return doc


async def _get(report_id: str) -> dict:
    doc = await db.reports.find_one({"_id": report_id})
    if not doc:
        raise HTTPException(404, "Report not found")
    return doc


@router.post("")
async def create(req: ReportRequest):
    msg = await db.messages.find_one({"session_id": req.session_id, "id": req.message_id, "role": "assistant"}, {"_id": 0})
    if not msg:
        raise HTTPException(404, "Investigation not found")
    try:
        report = await run_in_threadpool(generate_report, msg)
    except Exception as e:
        raise HTTPException(502, f"Report generation failed ({e})")
    doc = {"_id": uuid.uuid4().hex, "session_id": req.session_id, "message_id": req.message_id,
           "created_at": datetime.now(timezone.utc).isoformat(), **report}
    await db.reports.insert_one(doc)
    return _public(doc)


@router.get("")
async def list_reports():
    fields = {"title": 1, "created_at": 1, "question": 1, "verification.status": 1}
    return [_public(d) async for d in db.reports.find({}, fields).sort("created_at", -1).limit(50)]


@router.get("/{report_id}")
async def get_report(report_id: str):
    return _public(await _get(report_id))


@router.delete("/{report_id}")
async def delete_report(report_id: str):
    await _get(report_id)
    await db.reports.delete_one({"_id": report_id})
    return {"deleted": report_id}


def _download(doc: dict, ext: str, media: str, data: bytes) -> Response:
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", doc["title"]).strip("_")[:60] or "report"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}.{ext}"'})


@router.get("/{report_id}/pdf")
async def pdf(report_id: str):
    doc = await _get(report_id)
    return _download(doc, "pdf", "application/pdf", await run_in_threadpool(export.report_pdf, doc))


@router.get("/{report_id}/xlsx")
async def xlsx(report_id: str):
    doc = await _get(report_id)
    return _download(doc, "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     await run_in_threadpool(export.report_xlsx, doc))
