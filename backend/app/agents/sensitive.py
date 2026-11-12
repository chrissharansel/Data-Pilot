"""Detects and masks sensitive row-level data. Pure functions, no LLM.

What counts as sensitive: values under personal/financial column names (email, phone, salary, card, ...) in row-level
tool output, plus values that LOOK sensitive anywhere (emails, SSNs, Aadhaar numbers, Luhn-valid card numbers,
international phone numbers). Aggregates such as sum(salary) by department are statistics, not row-level, so they pass.
Limits: names are not detected (too many false positives), and detection is heuristic, not a compliance guarantee."""
import re

TOKENS = {"email", "mail", "phone", "mobile", "tel", "ssn", "aadhaar", "aadhar", "passport", "salary", "wage",
          "password", "passwd", "iban", "dob", "birth", "birthdate", "card", "cvv", "pan", "address", "acct"}
ROW_TOOLS = {"filter_rows", "top_n", "find_anomalies", "check_consistency", "compare_datasets"}
REDACTED = "[REDACTED]"

PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "aadhaar": re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b"),
    "phone": re.compile(r"\+\d{1,3}[\s-]?\(?\d{2,5}\)?[\s-]?\d{3,5}[\s-]?\d{3,5}"),
}
CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
KV = re.compile(r'("([^"\\]+)"\s*:\s*)("(?:[^"\\]|\\.)*"|-?\d[\d.eE+-]*|null|true|false)')


def _tokens(name: str) -> set[str]:
    return set(re.findall(r"[a-z]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", str(name)).lower()))


def is_sensitive_name(name: str) -> bool:
    return bool(_tokens(name) & TOKENS)


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total, alt = total + d, not alt
    return total % 10 == 0


def _is_card(match: str) -> bool:
    digits = re.sub(r"\D", "", match)
    return 13 <= len(digits) <= 19 and _luhn(digits)


def pattern_hits(text: str) -> set[str]:
    hits = {name for name, rx in PATTERNS.items() if rx.search(text)}
    if any(_is_card(m.group(0)) for m in CARD.finditer(text)):
        hits.add("card")
    return hits


def mask_text(text: str) -> str:
    for name, rx in PATTERNS.items():
        text = rx.sub(f"[REDACTED:{name}]", text)
    return CARD.sub(lambda m: "[REDACTED:card]" if _is_card(m.group(0)) else m.group(0), text)


def _redact_kv(text: str) -> str:
    """Replace the value of every sensitive-named key. Works on truncated JSON too (no parsing)."""
    return KV.sub(lambda m: f'{m.group(1)}"{REDACTED}"' if is_sensitive_name(m.group(2)) else m.group(0), text)


def sensitive_columns(tool: str, text: str) -> set[str]:
    if tool not in ROW_TOOLS:
        return set()
    return {m.group(2) for m in KV.finditer(text) if is_sensitive_name(m.group(2))}


def mask_result(tool: str, text: str) -> str:
    return mask_text(_redact_kv(text) if tool in ROW_TOOLS else text)


# ---------- scan / apply ----------
def scan(evidence: list[dict], sources: list[dict], charts: list[dict]) -> list[dict]:
    findings = []
    for e in evidence:
        cols, pats = sensitive_columns(e["tool"], e["result"]), pattern_hits(e["result"])
        if cols or pats:
            findings.append({"id": e["id"], "kind": "evidence", "label": f"{e['id']} {e['tool']}",
                             "columns": sorted(cols), "patterns": sorted(pats)})
    for s in sources:
        pats = pattern_hits(s["snippet"])
        if pats:
            findings.append({"id": str(s["n"]), "kind": "source", "label": f"document passage [{s['n']}] {s['filename']}",
                             "columns": [], "patterns": sorted(pats)})
    for c in charts:  # an anomaly scatter plots every row's value, so a sensitive column is row-level data
        if c["title"].startswith("Anomalies in ") and is_sensitive_name(c["title"][len("Anomalies in "):]):
            findings.append({"id": c["id"], "kind": "chart", "label": f"chart: {c['title']}", "columns": [], "patterns": []})
    return findings


def apply(decision: str, findings: list[dict], evidence: list[dict], sources: list[dict], charts: list[dict]):
    flagged = {(f["kind"], f["id"]) for f in findings}
    if decision == "approve":
        return evidence, sources, charts
    keep_charts = [c for c in charts if ("chart", c["id"]) not in flagged]
    if decision == "reject":
        return ([e for e in evidence if ("evidence", e["id"]) not in flagged],
                [s for s in sources if ("source", str(s["n"])) not in flagged], keep_charts)
    masked_ev = [{**e, "args": {k: mask_text(str(v)) if isinstance(v, str) else v for k, v in e["args"].items()},
                  "result": mask_result(e["tool"], e["result"])} for e in evidence]
    masked_src = [{**s, "snippet": mask_text(s["snippet"])} for s in sources]
    return masked_ev, masked_src, keep_charts
