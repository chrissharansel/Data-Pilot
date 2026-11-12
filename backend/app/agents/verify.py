"""Verification logic. Deterministic checks (no LLM) catch the failures small models make most often:
citations that point at nothing, and numbers that appear nowhere in the evidence."""
import re

CITE = re.compile(r"\[\s*([DI]?\d+(?:\s*,\s*[DI]?\d+)*)\s*\]")
NUM = re.compile(r"(?<![\w.])-?\$?\d[\d,]*(?:\.\d+)?%?")
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
VERDICTS = {"supported", "partial", "unsupported"}


def cite_ids(text: str) -> list[str]:
    out = []
    for m in CITE.finditer(text):
        out += [x.strip() for x in m.group(1).split(",")]
    return out


def numbers(text: str) -> list[tuple[str, float, bool]]:
    """(token, value, is_percent) for every number in text, ignoring [citation] brackets."""
    found = []
    for m in NUM.finditer(CITE.sub(" ", text)):
        tok = m.group(0)
        raw = tok.replace("$", "").replace(",", "").rstrip("%")
        try:
            found.append((tok, float(raw), tok.endswith("%")))
        except ValueError:
            continue
    return found


def _grounded(value: float, is_pct: bool, pool: list[float]) -> bool:
    cands = [value, value / 100] if is_pct else [value]
    return any(abs(c - p) <= max(0.011, 0.005 * abs(p)) for c in cands for p in pool)


def check_answer(answer: str, question: str, evidence: list[dict], sources: list[dict]) -> dict:
    known = {e["id"] for e in evidence} | {str(s["n"]) for s in sources}
    used = cite_ids(answer)
    invalid = sorted({c for c in used if c not in known})

    corpus = " ".join([question] + [e["result"] for e in evidence] + [s["snippet"] for s in sources])
    pool = [v for _, v, _ in numbers(corpus)]
    question_nums = {v for _, v, _ in numbers(question)}

    def checkable(tok, val, pct):  # tiny whole numbers ("top 3", "2 steps") are not worth flagging
        return pct or not (float(val).is_integer() and abs(val) <= 10) and val not in question_nums

    ungrounded, claims = [], []
    for sent in (s.strip() for s in SENTENCE.split(answer)):
        if not sent:
            continue
        cites = cite_ids(sent)
        nums = [(t, v, p) for t, v, p in numbers(sent) if checkable(t, v, p)]
        bad_nums = [t for t, v, p in nums if not _grounded(v, p, pool)]
        ungrounded += bad_nums
        if not cites and not nums:
            continue
        bad_cites = [c for c in cites if c not in known]
        if bad_cites or bad_nums:
            verdict = "unsupported"
            note = "; ".join(filter(None, [f"unknown citation {', '.join(bad_cites)}" if bad_cites else "",
                                           f"number(s) not in evidence: {', '.join(bad_nums)}" if bad_nums else ""]))
        elif cites:
            verdict, note = "supported", "citations exist and numbers match the evidence"
        else:
            verdict, note = "partial", "numbers match the evidence but the sentence has no citation"
        claims.append({"claim": sent[:240], "verdict": verdict, "evidence": sorted(set(cites)), "note": note})
    return {"used": used, "invalid": invalid, "ungrounded": sorted(set(ungrounded)), "claims": claims}


def summarize(det: dict, llm_claims: list[dict] | None = None) -> dict:
    claims = [dict(c) for c in (llm_claims or det["claims"])]
    bad = det["ungrounded"]
    for c in claims:  # an LLM "supported" verdict never overrides a number that isn't in the evidence
        if c["verdict"] == "supported" and any(t in c["claim"] for t in bad):
            c["verdict"], c["note"] = "partial", (c.get("note", "") + " (contains a number not found in the evidence)").strip()
    n = len(claims)
    score = sum({"supported": 1, "partial": 0.5}.get(c["verdict"], 0) for c in claims) / n if n else 0.0
    issues = []
    if det["invalid"]:
        issues.append(f"Citation(s) {', '.join(det['invalid'])} do not match any evidence.")
    if bad:
        issues.append(f"Number(s) not found in the evidence: {', '.join(bad)}.")
    if not det["used"]:
        issues.append("The answer contains no citations.")
    if not n:
        status = "unverified"
    elif det["invalid"] or score < 0.4:
        status = "unverified"
    elif score >= 0.8 and not bad and det["used"]:
        status = "verified"
    else:
        status = "partially_verified"
    return {"status": status, "support_score": round(score * 100), "claims": claims, "issues": issues,
            "ungrounded_numbers": bad, "invalid_citations": det["invalid"]}


def needs_revision(v: dict) -> bool:
    return v["status"] == "unverified" or bool(v["ungrounded_numbers"]) or bool(v["invalid_citations"])


def revision_notes(v: dict) -> str:
    notes = list(v["issues"])
    notes.append("Use only numbers that appear in the evidence, cite every factual sentence with valid ids, "
                 "and if you derive a value (e.g. a difference) say so and show the calculation.")
    return " ".join(notes)


def parse_llm_claims(parsed: dict, known_ids: set[str]) -> list[dict] | None:
    out = []
    for c in (parsed.get("claims") or [])[:8]:
        if not isinstance(c, dict) or not c.get("claim"):
            continue
        verdict = str(c.get("verdict", "")).lower()
        out.append({"claim": str(c["claim"])[:240], "verdict": verdict if verdict in VERDICTS else "partial",
                    "evidence": [str(e) for e in (c.get("evidence") or []) if str(e) in known_ids],
                    "note": str(c.get("note", ""))[:240]})
    return out or None
