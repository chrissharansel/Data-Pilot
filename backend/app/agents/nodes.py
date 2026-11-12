"""LangGraph nodes. Each node reads the shared state and returns a partial update plus log entries."""
import json
import re
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.types import interrupt

from ..config import settings
from ..rag.pipeline import retrieve
from ..services.llm import clean, get_llm
from . import memory, sensitive, verify
from .charts import bar_from_aggregate
from .inv_tools import make_investigation_tools
from .state import REPLACE, InvestigationState
from .tools import catalog_text, make_tools

AGENTS = ("data", "investigate", "rag")  # execution order
MAX_REVISIONS = 1

recall_memories = memory.recall  # module-level name so tests can swap it

PLANNER_PROMPT = """You plan investigations over the user's uploaded files.
Files:
{catalog}

Agents you can assign:
- data: computes exact numbers on datasets with Pandas tools (totals, averages, group-bys, filters, top-N, missing values).
- investigate: finds anomalies/outliers (z-score, IQR, Isolation Forest), trends over time, data-quality problems, and mismatches between two datasets.
- rag: searches the text of uploaded documents and dataset summaries for relevant passages.

Return ONLY JSON: {{"objective": "<one sentence>", "steps": [{{"agent": "data" or "investigate" or "rag", "task": "<specific instruction>"}}]}}
Use data for plain numeric questions. Use investigate for anything about unusual values, fraud-like patterns, trends, quality, duplicates or reconciling datasets.
Use rag for policies, definitions, explanations or text. Combine agents when the question needs it. At most one step per agent. /no_think"""

DATA_PROMPT = """You are the Data Agent. Answer the task using ONLY the tools; never guess numbers.
Datasets:
{catalog}
Call tools as needed. When finished, reply with a short factual summary containing the exact numbers the tools returned. /no_think"""

INVESTIGATE_PROMPT = """You are the Investigation Agent. Find anomalies, trends, data-quality problems and cross-dataset mismatches using ONLY the tools; never guess.
Datasets:
{catalog}
Tools: find_anomalies, analyze_trend, check_consistency, compare_datasets. Choose the ones that fit the task (usually 1-3 calls).
Finish with a short factual summary listing exact figures and row numbers. Say clearly when nothing unusual was found. /no_think"""

VERIFIER_PROMPT = """You are the Verification Agent. Check the answer against the evidence only.
List up to 6 key factual claims from the answer. For each give a verdict: "supported" (the evidence states it),
"partial" (only partly supported, or an inference), or "unsupported" (not in the evidence, or contradicted), the evidence ids that apply, and a one-sentence note.
Return ONLY JSON: {{"claims": [{{"claim": "...", "verdict": "supported|partial|unsupported", "evidence": ["D1"], "note": "..."}}]}} /no_think"""

WRITER_PROMPT = """You are DataPilot, a careful analyst writing the final answer from collected evidence only.
Cite calculated results as [D1], [I1] etc. and document passages as [1], [2]. Charts are shown next to your answer; refer to them by title when useful.
If evidence is missing or weak, say so. Never invent numbers or rows. Past findings, if shown, are background only: do not cite them or reuse their numbers unless the current evidence confirms them.
Values shown as [REDACTED] were hidden on purpose; do not guess them. Be concise and lead with the answer. /no_think"""


def _log(agent: str, action: str, detail: str = "") -> dict:
    return {"agent": agent, "action": action, "detail": detail, "ts": datetime.now(timezone.utc).isoformat()}


def _short(s: str, n: int = 220) -> str:
    return s if len(s) <= n else s[:n] + "…"


def _history(state: InvestigationState) -> str:
    return "\n".join(f"{m['role']}: {m['content'][:400]}" for m in state.get("history", [])[-4:]) or "(none)"


def _memory_text(state: InvestigationState) -> str:
    return "\n".join(f"- Q: {m['question']} -> {m['summary'][:300]}" for m in state.get("memories", []))


def _task(state: InvestigationState, agent: str) -> str:
    return next((s["task"] for s in state.get("plan", {}).get("steps", []) if s["agent"] == agent), state["question"])


# ---------- Memory recall ----------
def recall_node(state: InvestigationState) -> dict:
    if not state.get("use_memory", True):
        return {"memories": [], "logs": []}
    names = [d["filename"] for d in state.get("datasets", [])] + [d["filename"] for d in state.get("documents", [])]
    found = recall_memories(state["question"], names)
    logs = [_log("memory", f"Recalled {len(found)} related past finding(s)",
                 "; ".join(m["question"][:80] for m in found))] if found else []
    return {"memories": found, "logs": logs}


# ---------- Planner ----------
def _fallback_plan(question: str, datasets: list, documents: list) -> dict:
    steps = []
    if datasets:
        steps.append({"agent": "data", "task": question})
    if documents or not datasets:
        steps.append({"agent": "rag", "task": question})
    return {"objective": question, "steps": steps, "fallback": True}


def _sanitize(plan, question: str, datasets: list, documents: list) -> dict:
    if not isinstance(plan, dict):
        return _fallback_plan(question, datasets, documents)
    steps, seen = [], set()
    for s in plan.get("steps") or []:
        if not isinstance(s, dict):
            continue
        agent, task = str(s.get("agent", "")).strip().lower(), str(s.get("task") or question).strip()
        if agent not in AGENTS or agent in seen:
            continue
        if agent in {"data", "investigate"} and not datasets:
            continue  # these agents need tables
        if agent == "rag" and not (documents or datasets):
            continue
        seen.add(agent)
        steps.append({"agent": agent, "task": task})
    if not steps:
        return _fallback_plan(question, datasets, documents)
    steps.sort(key=lambda s: AGENTS.index(s["agent"]))
    return {"objective": str(plan.get("objective") or question), "steps": steps}


def planner_node(state: InvestigationState) -> dict:
    datasets, documents, q = state.get("datasets", []), state.get("documents", []), state["question"]
    plan = None
    try:
        msgs = [SystemMessage(PLANNER_PROMPT.format(catalog=catalog_text(datasets, documents))),
                HumanMessage(f"Conversation so far:\n{_history(state)}\n"
                     + (f"\nRelated past findings (context only, may be outdated):\n{_memory_text(state)}\n" if state.get("memories") else "")
                     + f"\nQuestion: {q}")]
        raw = clean(get_llm(json_mode=True).invoke(msgs).content)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        plan = json.loads(m.group(0)) if m else None
    except Exception:
        plan = None
    plan = _sanitize(plan, q, datasets, documents)
    detail = "; ".join(f"{s['agent']}: {s['task']}" for s in plan["steps"])
    note = " (model gave no usable plan, used default)" if plan.get("fallback") else ""
    return {"plan": plan, "logs": [_log("planner", f"Planned {len(plan['steps'])} step(s){note}", detail)]}


# ---------- shared tool-calling loop ----------
def _run_tool_loop(agent: str, system: str, task: str, tools: list, prefix: str, on_success=None):
    tool_map = {t.name: t for t in tools}
    llm = get_llm().bind_tools(tools)
    msgs = [SystemMessage(system), HumanMessage(task)]
    logs, evidence, ai = [_log(agent, "Started", task)], [], None

    for _ in range(settings.max_agent_steps):
        ai = llm.invoke(msgs)
        msgs.append(ai)
        if not ai.tool_calls:
            break
        for tc in ai.tool_calls:
            name, args = tc["name"], tc["args"]
            if name not in tool_map:
                result = json.dumps({"error": f"Unknown tool '{name}'. Use one of {list(tool_map)}"})
            else:
                try:
                    result = tool_map[name].invoke(args)
                except Exception as e:
                    result = json.dumps({"error": str(e)})
            if result.startswith('{"error"'):
                logs.append(_log(agent, f"Tool {name} failed", f"{sensitive.mask_text(json.dumps(args))} → {_short(result)}"))
            else:
                ev_id = f"{prefix}{len(evidence) + 1}"
                evidence.append({"id": ev_id, "tool": name, "args": args, "result": result})
                # logs are streamed to the browser before the approval gate runs, so they only ever carry masked values
                logs.append(_log(agent, f"Ran {name}", f"{ev_id}: {sensitive.mask_text(json.dumps(args))} → {_short(sensitive.mask_result(name, result))}"))
                if on_success:
                    on_success(name, args, result)
            msgs.append(ToolMessage(content=result, tool_call_id=tc.get("id") or name))

    if ai is None or ai.tool_calls:  # hit the step limit mid-investigation: force a summary
        ai = get_llm().invoke(msgs + [HumanMessage("Step limit reached. Summarise what the tool results show so far.")])
    return clean(ai.content), evidence, logs


# ---------- Data Agent ----------
def data_agent_node(state: InvestigationState) -> dict:
    datasets, charts = state["datasets"], []

    def on_success(name, args, result):
        if name == "aggregate" and args.get("group_by"):
            c = bar_from_aggregate(result)
            if c:
                charts.append({"id": f"DC{len(charts) + 1}", **c})

    findings, evidence, logs = _run_tool_loop(
        "data", DATA_PROMPT.format(catalog=catalog_text(datasets, [])), _task(state, "data"),
        make_tools(datasets), "D", on_success)
    logs += [_log("data", f"Created chart {c['id']}", c["title"]) for c in charts]
    logs.append(_log("data", "Finished", f"{len(evidence)} calculation(s)"))
    return {"data_findings": findings, "evidence": evidence, "charts": charts, "logs": logs}


# ---------- Investigation Agent ----------
def investigation_agent_node(state: InvestigationState) -> dict:
    datasets, charts = state["datasets"], []
    findings, evidence, logs = _run_tool_loop(
        "investigate", INVESTIGATE_PROMPT.format(catalog=catalog_text(datasets, [])), _task(state, "investigate"),
        make_investigation_tools(datasets, charts), "I")
    logs += [_log("investigate", f"Created chart {c['id']}", c["title"]) for c in charts]
    logs.append(_log("investigate", "Finished", f"{len(evidence)} analysis step(s), {len(charts)} chart(s)"))
    return {"investigation_findings": findings, "evidence": evidence, "charts": charts, "logs": logs}


# ---------- RAG Agent ----------
def rag_agent_node(state: InvestigationState) -> dict:
    task = _task(state, "rag")
    sources = retrieve(task, state.get("file_ids"), k=6)
    logs = [_log("rag", "Searching indexed files", f'query: "{task}"')]
    logs += [_log("rag", f"Retrieved [{s['n']}] {s['filename']}", f"{s['location']} (distance {s['score']})") for s in sources]
    if not sources:
        logs.append(_log("rag", "No passages found"))
    return {"sources": sources, "logs": logs}


# ---------- Approval gate (human in the loop) ----------
def approval_gate_node(state: InvestigationState) -> dict:
    """Pauses the run (LangGraph interrupt) when row-level sensitive data is about to reach the answer."""
    evidence, sources, charts = state.get("evidence", []), state.get("sources", []), state.get("charts", [])
    if settings.sensitive_policy == "allow":
        return {"approval": {"flagged": False, "policy": "allow"}, "logs": [_log("approval", "Sensitive-data check disabled", "policy: allow")]}
    findings = sensitive.scan(evidence, sources, charts)
    if not findings:
        return {"approval": {"flagged": False}, "logs": [_log("approval", "Sensitive-data check", "nothing flagged")]}

    summary = [{k: f[k] for k in ("id", "kind", "label", "columns", "patterns")} for f in findings]
    if settings.sensitive_policy == "mask":
        decision, by = "mask", "policy"
    else:
        answer = interrupt({"type": "sensitive_data", "title": "Approval needed: sensitive data",
                            "message": "The analysis produced row-level values that look sensitive. Choose how they should be handled before the answer is written.",
                            "findings": summary})
        decision = answer.get("decision") if isinstance(answer, dict) else answer
        decision, by = (decision if decision in {"approve", "mask", "reject"} else "mask"), "human"

    ev, src, ch = sensitive.apply(decision, findings, evidence, sources, charts)
    verb = {"approve": "approved showing the values", "mask": "masked the values", "reject": "excluded the flagged evidence"}[decision]
    out = {"evidence": [REPLACE, *ev], "sources": src, "charts": [REPLACE, *ch],
           "approval": {"flagged": True, "decision": decision, "decided_by": by, "findings": summary},
           "logs": [_log("approval", f"{'You' if by == 'human' else 'Policy'} {verb}", "; ".join(f["label"] for f in summary))]}
    if decision != "approve":  # agent summaries were written from raw values, so they must not reach the Writer
        out["data_findings"], out["investigation_findings"] = "", ""
        out["logs"].append(_log("approval", "Withheld agent summaries", "they were written before masking"))
    return out


# ---------- Writer (becomes the full Report Agent in Phase 4) ----------
def synthesizer_node(state: InvestigationState) -> dict:
    evidence, sources, charts = state.get("evidence", []), state.get("sources", []), state.get("charts", [])
    if not evidence and not sources:
        return {"answer": "I couldn't find evidence for this in the selected files. Try selecting different files or rephrasing.",
                "logs": [_log("writer", "No evidence collected")]}
    parts = [f"Question: {state['question']}", f"Conversation so far:\n{_history(state)}"]
    if evidence:
        parts.append("Calculated results:\n" + "\n".join(
            f"[{e['id']}] {e['tool']} {json.dumps(e['args'])}\n{e['result']}" for e in evidence))
    for label, key in (("Data Agent summary", "data_findings"), ("Investigation Agent summary", "investigation_findings")):
        if state.get(key):
            parts.append(f"{label}: {state[key]}")
    if state.get("memories"):
        parts.append("Related past findings (NOT evidence, do not cite):\n" + _memory_text(state))
    if charts:
        parts.append("Charts shown to the user: " + "; ".join(c["title"] for c in charts))
    if sources:
        parts.append("Document excerpts:\n" + "\n\n".join(
            f"[{s['n']}] ({s['filename']} - {s['location']})\n{s['snippet']}" for s in sources))
    revising = bool(state.get("revision_notes"))
    if revising:
        parts.append(f"Your previous answer:\n{state.get('answer', '')}\n\nReviewer feedback you must fix:\n{state['revision_notes']}")
    reply = get_llm().invoke([SystemMessage(WRITER_PROMPT), HumanMessage("\n\n".join(parts))])
    action = "Revised answer after verification" if revising else "Wrote answer"
    return {"answer": clean(reply.content),
            "logs": [_log("writer", action, f"{len(evidence)} calculation(s), {len(sources)} passage(s), {len(charts)} chart(s)")]}


# ---------- Verification Agent ----------
def verifier_node(state: InvestigationState) -> dict:
    answer, evidence, sources = state.get("answer", ""), state.get("evidence", []), state.get("sources", [])
    if not evidence and not sources:
        return {"verification": {"status": "not_applicable", "support_score": 0, "claims": [], "issues": [],
                                 "ungrounded_numbers": [], "invalid_citations": []},
                "revision_notes": "", "logs": [_log("verifier", "Skipped", "no evidence was collected")]}

    det = verify.check_answer(answer, state["question"], evidence, sources)
    prelim = verify.summarize(det)
    revisions = state.get("revisions", 0)
    logs = [_log("verifier", f"Checked {len(det['claims'])} claim(s) against evidence",
                 f"{len(det['used'])} citation(s), {len(det['invalid'])} invalid, {len(det['ungrounded'])} number(s) not in evidence")]

    if verify.needs_revision(prelim) and revisions < MAX_REVISIONS:  # fail fast: no need to spend an LLM call
        logs.append(_log("verifier", "Requested revision", " ".join(prelim["issues"]) or "answer is not supported by the evidence"))
        return {"verification": prelim, "revision_notes": verify.revision_notes(prelim), "revisions": revisions + 1, "logs": logs}

    llm_claims = None
    try:
        known = {e["id"] for e in evidence} | {str(s["n"]) for s in sources}
        ev_text = "\n".join(f"[{e['id']}] {e['tool']} {json.dumps(e['args'])}\n{e['result'][:800]}" for e in evidence)
        src_text = "\n".join(f"[{s['n']}] ({s['filename']} - {s['location']}) {s['snippet'][:500]}" for s in sources)
        raw = clean(get_llm(json_mode=True).invoke([
            SystemMessage(VERIFIER_PROMPT),
            HumanMessage(f"Evidence:\n{ev_text}\n{src_text}\n\nAnswer to check:\n{answer}")]).content)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        llm_claims = verify.parse_llm_claims(json.loads(m.group(0)), known) if m else None
    except Exception:
        llm_claims = None  # fall back to the deterministic claim list
    result = verify.summarize(det, llm_claims)
    logs.append(_log("verifier", f"Verdict: {result['status'].replace('_', ' ')}",
                     f"support score {result['support_score']}%" + ("" if llm_claims else " (rule-based check; model check unavailable)")))
    return {"verification": result, "revision_notes": "", "logs": logs}
