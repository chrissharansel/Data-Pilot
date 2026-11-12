"""Report Agent: turns a saved, verified investigation into a structured report.
The model writes the title, summary, findings and recommendations; everything factual around it (methodology,
limitations, verification status, evidence) is assembled deterministically so it cannot be hallucinated."""
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import settings
from ..services.llm import clean, get_llm
from . import verify

REPORT_PROMPT = """You are the Report Agent. Write a concise business report from a finished investigation.
Use ONLY the answer and evidence provided. Do not add numbers that are not in them.
Return ONLY JSON: {{"title": "<max 80 chars>", "executive_summary": "<2-4 sentences>",
"findings": [{{"text": "<one finding>", "refs": ["D1", "I1", "1"]}}],
"recommendations": ["<action that follows directly from a finding>"]}}
3-6 findings, each citing the evidence ids it relies on. Recommendations must be practical and traceable to findings. /no_think"""


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in verify.SENTENCE.split(text) if len(s.strip()) > 3]


def _fallback(msg: dict, known: set[str]) -> dict:
    answer = msg.get("content", "")
    sents = _sentences(answer)
    cited = [s for s in sents if verify.cite_ids(s)] or sents
    findings = [{"text": verify.CITE.sub("", s).strip(), "refs": sorted(set(verify.cite_ids(s)) & known)} for s in cited[:8]]
    return {"title": (msg.get("question") or "Investigation report")[:80], "executive_summary": " ".join(sents[:2])[:600],
            "findings": findings, "recommendations": []}


def _recommendations_fallback(evidence: list[dict], ver: dict) -> list[str]:
    recs = []
    tools = {e["tool"] for e in evidence}
    if "find_anomalies" in tools:
        recs.append("Review the flagged rows listed in the Anomalies appendix with the data owner to confirm whether they are errors or genuine events.")
    if "check_consistency" in tools:
        recs.append("Resolve the data-quality issues found (duplicates, spelling variants, unexpected values) before relying on totals from this data.")
    if "compare_datasets" in tools:
        recs.append("Reconcile the keys present in only one dataset to find missing or mis-keyed records.")
    recs += [f"Manually confirm before acting: {i}" for i in ver.get("issues", [])]
    return recs or ["No specific action follows from this investigation. Extend it with additional files if needed."]


def _limitations(msg: dict) -> list[str]:
    evidence, sources, ver = msg.get("evidence") or [], msg.get("sources") or [], msg.get("verification") or {}
    files = sorted({e["args"].get("dataset", "") for e in evidence if isinstance(e.get("args"), dict)} - {""}
                   | {s["filename"] for s in sources})
    out = ["Findings are based only on the files uploaded for this investigation" + (f": {', '.join(files)}." if files else ".")]
    if any(e["tool"] == "find_anomalies" for e in evidence):
        out.append("Isolation Forest flags the ~2% most isolated rows by design; only rows flagged by several methods are strong signals. Statistical outliers are not necessarily errors.")
    if sources:
        out.append("Document passages are found by semantic similarity and may miss relevant text that is worded differently.")
    appr = msg.get("approval") or {}
    if appr.get("flagged"):
        how = {"approve": "shown as-is after the user approved it", "mask": "masked", "reject": "excluded from the analysis"}.get(appr.get("decision"), "handled")
        out.append(f"Sensitive row-level data was detected and {how} ({'by policy' if appr.get('decided_by') == 'policy' else 'user decision'}). "
                   "Detection is heuristic and does not replace a data-protection review.")
    status = ver.get("status")
    if status and status not in {"verified", "not_applicable"}:
        out.append(f"Verification status is '{status.replace('_', ' ')}'. Review the flagged issues before acting on the findings.")
    return out


def generate_report(msg: dict) -> dict:
    evidence, sources = msg.get("evidence") or [], msg.get("sources") or []
    known = {e["id"] for e in evidence} | {str(s["n"]) for s in sources}
    ver = msg.get("verification") or {}
    base = _fallback(msg, known)
    try:
        ev_text = "\n".join(f"[{e['id']}] {e['tool']} {json.dumps(e['args'])}\n{e['result'][:700]}" for e in evidence)
        src_text = "\n".join(f"[{s['n']}] ({s['filename']} - {s['location']}) {s['snippet'][:400]}" for s in sources)
        raw = clean(get_llm(json_mode=True).invoke([
            SystemMessage(REPORT_PROMPT),
            HumanMessage(f"Question: {msg.get('question', '')}\n\nVerified answer:\n{msg.get('content', '')}\n\nEvidence:\n{ev_text}\n{src_text}")]).content)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        findings = [{"text": str(f.get("text", "")).strip(), "refs": [str(r) for r in (f.get("refs") or []) if str(r) in known]}
                    for f in (data.get("findings") or []) if isinstance(f, dict) and str(f.get("text", "")).strip()][:8]
        recs = [str(r).strip() for r in (data.get("recommendations") or []) if str(r).strip()][:6]
        base = {"title": str(data.get("title") or base["title"])[:80],
                "executive_summary": str(data.get("executive_summary") or base["executive_summary"])[:900],
                "findings": findings or base["findings"], "recommendations": recs}
    except Exception:
        pass  # keep the deterministic report
    if not base["recommendations"]:
        base["recommendations"] = _recommendations_fallback(evidence, ver)

    plan = msg.get("plan") or {}
    logs = msg.get("logs") or []
    return {
        **base,
        "question": msg.get("question", ""),
        "objective": plan.get("objective", ""),
        "methodology": [f"{s['agent']}: {s['task']}" for s in plan.get("steps", [])]
                       + [f"{len(evidence)} tool call(s) and {len(sources)} document passage(s) used as evidence; {len(logs)} agent steps logged."],
        "limitations": _limitations(msg),
        "verification": ver,
        "evidence": evidence, "sources": sources, "charts": msg.get("charts") or [],
        "model": settings.ollama_model,
    }
