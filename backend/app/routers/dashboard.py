from fastapi import APIRouter

from .. import db
from ..services.dashboard import chart_gallery, datasets_overview

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
INVESTIGATION = {"role": "assistant", "verification": {"$exists": True}}


@router.get("")
async def dashboard():
    files = [f async for f in db.files.find({}, {"filename": 1, "kind": 1, "profile": 1})]
    breakdown = {}
    cursor = await db.messages.aggregate([{"$match": INVESTIGATION}, {"$group": {"_id": "$verification.status", "n": {"$sum": 1}}}])
    async for d in cursor:
        breakdown[d["_id"] or "unknown"] = d["n"]
    recent = [m async for m in db.messages.find(INVESTIGATION, {"_id": 0, "id": 1, "session_id": 1, "question": 1, "charts": 1, "ts": 1})
              .sort("ts", -1).limit(40)]
    return {
        "counts": {"files": len(files), "tabular": sum(f["kind"] == "tabular" for f in files),
                   "investigations": sum(breakdown.values()), "reports": await db.reports.count_documents({}),
                   "memories": await db.memories.count_documents({}),
                   "sensitive_flagged": await db.messages.count_documents({**INVESTIGATION, "approval.flagged": True})},
        "verification": breakdown,
        "datasets": datasets_overview(files),
        "charts": chart_gallery(recent),
    }
