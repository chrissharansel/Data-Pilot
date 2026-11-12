"""Cross-session memory. Verified findings are remembered and recalled as CONTEXT for later questions.
Memory is never evidence: the Writer is told not to cite it, and the Verifier only trusts current-run evidence."""
import re
import uuid
from datetime import datetime, timezone

from ..config import settings
from ..services import vectorstore
from . import verify


def build(question: str, answer: str, files: list[str], status: str, session_id: str) -> dict:
    summary = re.sub(r"\s+", " ", verify.CITE.sub("", answer)).strip()[:700]
    mid, now = uuid.uuid4().hex, datetime.now(timezone.utc).isoformat()
    files = sorted(set(files))
    return {"id": mid, "text": f"{question}\n{summary}",
            "meta": {"memory_id": mid, "question": question[:300], "summary": summary, "files": "|".join(files), "created_at": now},
            "doc": {"_id": mid, "question": question, "summary": summary, "files": files, "status": status,
                    "session_id": session_id, "created_at": now}}


def recall(question: str, filenames: list[str], k: int | None = None) -> list[dict]:
    k = k or settings.memory_top_k
    try:
        hits = vectorstore.search_memory(question, k * 2)
    except Exception:
        return []
    current, out = set(filenames), []
    for doc, score in hits:
        if score > settings.memory_max_distance:
            continue
        files = {f for f in doc.metadata.get("files", "").split("|") if f}
        if current and files and not (files & current):  # a finding about other files could mislead
            continue
        out.append({"id": doc.metadata.get("memory_id"), "question": doc.metadata.get("question", ""),
                    "summary": doc.metadata.get("summary", ""), "files": sorted(files), "score": round(float(score), 3)})
    return out[:k]
