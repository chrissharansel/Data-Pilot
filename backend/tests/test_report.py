import json
from io import BytesIO

import pytest
from langchain_core.messages import AIMessage
from openpyxl import load_workbook

from app.agents import report as report_mod
from app.agents import charts
from app.services import export


from .test_agents import FakeLLM


@pytest.fixture
def msg():
    fig = charts.bar_from_aggregate(json.dumps({"operation": "sum(amount) by region", "result": {"S": 5110, "N": 300}}))
    anomalies = {"top_anomalies": [{"row_number": 52, "flagged_by": ["iqr", "zscore"], "values": {"amount": 900}}]}
    return {
        "question": "Which region sells most and are there outliers?", "role": "assistant",
        "content": "South leads with 5110 [D1]. Row 52 is a clear outlier [I1].",
        "plan": {"objective": "Sales by region and outliers", "steps": [{"agent": "data", "task": "sum"}, {"agent": "investigate", "task": "outliers"}]},
        "evidence": [{"id": "D1", "tool": "aggregate", "args": {"dataset": "orders.csv"}, "result": '{"result": {"S": 5110, "N": 300}}'},
                     {"id": "I1", "tool": "find_anomalies", "args": {"dataset": "orders.csv"}, "result": json.dumps(anomalies)}],
        "sources": [], "charts": [{"id": "DC1", **fig}], "logs": [{}] * 7,
        "verification": {"status": "verified", "support_score": 100, "issues": [],
                         "claims": [{"claim": "South leads", "verdict": "supported", "evidence": ["D1"], "note": ""}]},
    }


def test_llm_report_filters_unknown_refs(monkeypatch, msg):
    data = {"title": "Regional sales", "executive_summary": "South leads.", "recommendations": ["Check row 52."],
            "findings": [{"text": "South leads with 5110.", "refs": ["D1", "Z9"]}]}
    monkeypatch.setattr(report_mod, "get_llm", lambda *a, **k: FakeLLM([AIMessage(content=json.dumps(data))]))
    r = report_mod.generate_report(msg)
    assert r["title"] == "Regional sales" and r["findings"][0]["refs"] == ["D1"]  # invented ref Z9 dropped
    assert any("Isolation Forest" in x for x in r["limitations"])  # deterministic limitation added from tools used


def test_fallback_report_when_model_fails(monkeypatch, msg):
    monkeypatch.setattr(report_mod, "get_llm", lambda *a, **k: FakeLLM([AIMessage(content="not json")]))
    r = report_mod.generate_report(msg)
    assert r["findings"][0]["refs"] == ["D1"] and "5110" in r["findings"][0]["text"]
    assert any("Anomalies appendix" in x for x in r["recommendations"])


def test_pdf_and_excel_exports(monkeypatch, msg):
    monkeypatch.setattr(report_mod, "get_llm", lambda *a, **k: FakeLLM([AIMessage(content="x")]))
    r = report_mod.generate_report(msg)
    pdf = export.report_pdf(r)
    assert pdf[:4] == b"%PDF" and len(pdf) > 3000
    wb = load_workbook(BytesIO(export.report_xlsx(r)))
    assert {"Summary", "Verification", "Evidence", "Anomalies", "Charts", "Chart data"} <= set(wb.sheetnames)
    assert wb["Anomalies"]["B2"].value == 52
    assert len(wb["Charts"]._images) == 1


def test_excel_never_stores_formulas(monkeypatch, msg):
    monkeypatch.setattr(report_mod, "get_llm", lambda *a, **k: FakeLLM([AIMessage(content="x")]))
    r = report_mod.generate_report(msg)
    r["title"] = '=HYPERLINK("http://evil","click")'
    r["executive_summary"] = "=1+1"
    ws = load_workbook(BytesIO(export.report_xlsx(r)))["Summary"]
    assert ws["B1"].data_type == "s" and ws["B5"].data_type == "s"


def test_non_latin_text_does_not_crash_pdf(monkeypatch, msg):
    monkeypatch.setattr(report_mod, "get_llm", lambda *a, **k: FakeLLM([AIMessage(content="x")]))
    r = report_mod.generate_report(msg)
    r["executive_summary"] = "नमस्ते → results ↔ ok"
    assert export.report_pdf(r)[:4] == b"%PDF"
