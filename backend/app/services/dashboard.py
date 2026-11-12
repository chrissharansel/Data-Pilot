"""Pure helpers for the dashboard endpoint (kept free of database calls so they are easy to test)."""


def datasets_overview(files: list[dict]) -> list[dict]:
    out = []
    for f in files:
        if f.get("kind") != "tabular" or not f.get("profile"):
            continue
        sheets = f["profile"]["sheets"]
        rows = sum(s["rows"] for s in sheets)
        cells = sum(s["rows"] * len(s["columns"]) for s in sheets)
        nulls = sum(c["nulls"] for s in sheets for c in s["columns"])
        out.append({"id": f["_id"], "filename": f["filename"], "sheets": len(sheets), "rows": rows,
                    "columns": max(len(s["columns"]) for s in sheets),
                    "missing_pct": round(100 * nulls / cells, 2) if cells else 0.0})
    return out


def chart_gallery(messages: list[dict], limit: int = 12) -> list[dict]:
    out = []
    for m in messages:  # newest first
        for c in m.get("charts") or []:
            out.append({"id": f"{m.get('id', '')}-{c['id']}", "title": c["title"], "figure": c["figure"],
                        "question": m.get("question", ""), "session_id": m.get("session_id"), "ts": m.get("ts")})
            if len(out) >= limit:
                return out
    return out
