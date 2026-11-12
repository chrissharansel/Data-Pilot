"""PDF (ReportLab) and Excel (openpyxl) export of a report. Charts are redrawn with matplotlib from the Plotly JSON."""
import json
from io import BytesIO
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

STATUS = {"verified": ("Verified", "#2b9a66"), "partially_verified": ("Partially verified", "#b45f06"),
          "unverified": ("Unverified", "#d64545"), "not_applicable": ("Not applicable", "#667089")}
SWAPS = {"→": "->", "↔": "<->", "…": "...", "’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "•": "-"}


def _status(report: dict):
    return STATUS.get((report.get("verification") or {}).get("status"), ("Not verified", "#667089"))


def _t(s) -> str:
    """ReportLab's built-in fonts are Latin-1 only; swap common symbols, replace the rest."""
    s = str(s)
    for a, b in SWAPS.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def _p(s) -> str:
    return escape(_t(s))


# ---------- charts ----------
def figure_png(fig: dict, title: str) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    f, ax = plt.subplots(figsize=(7, 3.6), dpi=150)
    named = 0
    for tr in fig.get("data", []):
        kind, x, y = tr.get("type"), tr.get("x") or [], tr.get("y") or []
        marker, line = tr.get("marker") or {}, tr.get("line") or {}
        color = marker.get("color") if isinstance(marker.get("color"), (str, list)) else line.get("color")
        if kind == "bar":
            if tr.get("orientation") == "h":
                ax.barh(y, x, color=color)
                ax.invert_yaxis()
            else:
                ax.bar([str(v) for v in x], y, color=color)
        elif kind == "scatter":
            mode, label = tr.get("mode", "markers"), tr.get("name")
            if "lines" in mode:
                ax.plot(x, y, color=line.get("color") or color, linestyle="--" if line.get("dash") else "-",
                        marker="o" if "markers" in mode else None, markersize=4, label=label)
            else:
                ax.scatter(x, y, color=color, s=18, label=label)
            named += bool(label)
    lay = fig.get("layout", {})
    ax.set_title(title, fontsize=11, loc="left")
    ax.set_xlabel(((lay.get("xaxis") or {}).get("title") or {}).get("text", ""))
    ax.set_ylabel(((lay.get("yaxis") or {}).get("title") or {}).get("text", ""))
    ax.spines[["top", "right"]].set_visible(False)
    ax.xaxis.set_major_locator(MaxNLocator(8)) if any(isinstance(v, str) for tr in fig.get("data", []) for v in (tr.get("x") or [])[:1]) else None
    if named > 1:
        ax.legend(frameon=False, fontsize=8)
    plt.setp(ax.get_xticklabels(), rotation=25, ha="right", fontsize=8)
    f.tight_layout()
    buf = BytesIO()
    f.savefig(buf, format="png")
    plt.close(f)
    return buf.getvalue()


# ---------- PDF ----------
def report_pdf(r: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                            title=_t(r["title"]), author="DataPilot AI")
    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=10, leading=14)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=colors.HexColor("#1b2140"), spaceBefore=14)
    label, color = _status(r)
    ver = r.get("verification") or {}

    st = [Paragraph(_p(r["title"]), ss["Title"]),
          Paragraph(f"<b>Question:</b> {_p(r['question'])}", body), Spacer(1, 6)]
    badge = Table([[f"{label}" + (f"  |  support score {ver['support_score']}%" if "support_score" in ver and ver.get("status") != "not_applicable" else "")]])
    badge.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(color)), ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                               ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
                               ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    badge.hAlign = "LEFT"
    st += [badge, Paragraph("Executive summary", h2), Paragraph(_p(r["executive_summary"]), body), Paragraph("Key findings", h2)]
    for f in r["findings"]:
        refs = f" <font color='#667089'>[{_p(', '.join(f['refs']))}]</font>" if f["refs"] else ""
        st.append(Paragraph(_p(f["text"]) + refs, body, bulletText="-"))
    if r["charts"]:
        st.append(Paragraph("Charts", h2))
        for c in r["charts"]:
            st.append(KeepTogether([Image(BytesIO(figure_png(c["figure"], c["title"])), width=16 * cm, height=16 * cm * 3.6 / 7), Spacer(1, 6)]))
    st.append(Paragraph("Recommendations", h2))
    st += [Paragraph(_p(x), body, bulletText="-") for x in r["recommendations"]]
    st.append(Paragraph("Verification", h2))
    if ver.get("claims"):
        rows = [["Claim", "Verdict", "Evidence"]] + [[Paragraph(_p(c["claim"]), small), c["verdict"], ", ".join(c.get("evidence", []))] for c in ver["claims"]]
        t = Table(rows, colWidths=[10.5 * cm, 2.5 * cm, 4 * cm], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f6")), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9deea")),
                               ("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        st.append(t)
    for issue in ver.get("issues", []):
        st.append(Paragraph(_p(issue), body, bulletText="!"))
    if not ver.get("claims") and not ver.get("issues"):
        st.append(Paragraph("No verification details recorded.", body))
    st.append(Paragraph("Methodology", h2))
    st += [Paragraph(_p(m), body, bulletText="-") for m in r["methodology"]]
    st.append(Paragraph("Limitations", h2))
    st += [Paragraph(_p(m), body, bulletText="-") for m in r["limitations"]]
    if r["evidence"] or r["sources"]:
        st.append(Paragraph("Appendix: evidence", h2))
        rows = [["Id", "Tool", "Result"]] + [[e["id"], e["tool"], Paragraph(_p(e["result"][:450]), small)] for e in r["evidence"]]
        rows += [[str(s["n"]), s["filename"], Paragraph(_p(f"{s['location']}: {s['snippet'][:350]}"), small)] for s in r["sources"]]
        t = Table(rows, colWidths=[1.3 * cm, 3.4 * cm, 12.3 * cm], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f6")), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9deea")),
                               ("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        st.append(t)
    st.append(Spacer(1, 10))
    st.append(Paragraph(f"Generated by DataPilot AI with {_p(r.get('model', ''))}. Charts and numbers are computed from the uploaded files.", small))
    doc.build(st)
    return buf.getvalue()


# ---------- Excel ----------
HEAD = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="1B2140")
WRAP = Alignment(wrap_text=True, vertical="top")


def _set(ws, row, col, value, bold=False):
    c = ws.cell(row=row, column=col, value=value)
    if isinstance(value, str):
        c.data_type = "s"  # always text: content comes from uploaded files, so never let "=..." run as a formula
    c.alignment = WRAP
    if bold:
        c.font = Font(bold=True)
    return c


def _table(ws, start_row, headers, rows, widths):
    for i, h in enumerate(headers, 1):
        c = _set(ws, start_row, i, h)
        c.font, c.fill = HEAD, HEAD_FILL
    for r, row in enumerate(rows, start_row + 1):
        for i, v in enumerate(row, 1):
            _set(ws, r, i, v)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w


def report_xlsx(r: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    label, _ = _status(r)
    ver = r.get("verification") or {}
    row = 1
    for k, v in [("Title", r["title"]), ("Question", r["question"]), ("Verification", label),
                 ("Support score", f"{ver['support_score']}%" if ver.get("status") not in (None, "not_applicable") else "n/a"),
                 ("Executive summary", r["executive_summary"])]:
        _set(ws, row, 1, k, bold=True); _set(ws, row, 2, v); row += 1
    for title, items in [("Findings", [f["text"] + (f"  [{', '.join(f['refs'])}]" if f["refs"] else "") for f in r["findings"]]),
                         ("Recommendations", r["recommendations"]), ("Methodology", r["methodology"]), ("Limitations", r["limitations"])]:
        row += 1
        _set(ws, row, 1, title, bold=True)
        for it in items:
            _set(ws, row, 2, it); row += 1
        row += 0
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 20, 110

    _table(wb.create_sheet("Verification"), 1, ["Claim", "Verdict", "Evidence", "Note"],
           [[c["claim"], c["verdict"], ", ".join(c.get("evidence", [])), c.get("note", "")] for c in ver.get("claims", [])], [70, 14, 16, 50])
    _table(wb.create_sheet("Evidence"), 1, ["Id", "Tool", "Arguments", "Result"],
           [[e["id"], e["tool"], json.dumps(e["args"]), e["result"]] for e in r["evidence"]]
           + [[str(s["n"]), s["filename"], s["location"], s["snippet"]] for s in r["sources"]], [8, 22, 40, 100])

    anomalies = []
    for e in r["evidence"]:
        if e["tool"] == "find_anomalies":
            try:
                for a in json.loads(e["result"]).get("top_anomalies", []):
                    anomalies.append([e["id"], a["row_number"], ", ".join(a["flagged_by"]), json.dumps(a["values"])])
            except (ValueError, KeyError):
                pass
    if anomalies:
        _table(wb.create_sheet("Anomalies"), 1, ["Evidence", "Row number", "Flagged by", "Values"], anomalies, [10, 12, 36, 70])

    if r["charts"]:
        cs, data = wb.create_sheet("Charts"), []
        for i, c in enumerate(r["charts"]):
            img = XLImage(BytesIO(figure_png(c["figure"], c["title"])))
            img.width, img.height = 700, 360
            cs.add_image(img, f"A{1 + i * 20}")
            for tr in c["figure"].get("data", []):
                data += [[c["title"], tr.get("name") or "", str(x), y] for x, y in zip(tr.get("x") or [], tr.get("y") or [])]
        _table(wb.create_sheet("Chart data"), 1, ["Chart", "Series", "X", "Y"], data, [40, 20, 24, 16])

    out = BytesIO()
    wb.save(out)
    return out.getvalue()
