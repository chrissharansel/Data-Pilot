import json

import numpy as np
import pandas as pd
import pytest
from langchain_core.messages import AIMessage

from app.agents import analysis, charts, nodes
from app.agents.graph import build_graph
from app.agents.inv_tools import make_investigation_tools

from .test_agents import FakeLLM


@pytest.fixture
def sales():
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"id": range(1, 201), "amount": rng.normal(100, 5, 200).round(2),
                       "qty": rng.integers(1, 5, 200)})
    df.loc[50, "amount"] = 900.0  # planted outlier at spreadsheet row 52
    return df


def test_anomaly_detection_finds_planted_outlier(sales):
    report, chart = analysis.anomaly_report(sales)
    top = report["top_anomalies"][0]
    assert top["row_number"] == 52
    assert {"zscore", "iqr", "isolation_forest"} <= set(top["flagged_by"])
    assert "id" not in report["columns_analysed"]  # running-number id column is ignored
    assert chart["column"] == "amount"


def test_clean_data_reports_no_univariate_outliers():
    df = pd.DataFrame({"x": np.linspace(10, 11, 100)})
    report, _ = analysis.anomaly_report(df)
    assert report["per_column"]["x"]["zscore_outliers"] == 0


def test_trend_direction_and_jump():
    dates = pd.date_range("2024-01-01", periods=12, freq="MS")
    df = pd.DataFrame({"date": dates, "revenue": [100 + 20 * i for i in range(12)]})
    df.loc[8, "revenue"] = 600
    rep, c = analysis.trend_report(df, "date", "revenue")
    assert rep["direction"] == "rising" and rep["periods_analysed"] == 12
    assert rep["largest_period_jump"]["period"] == "2024-09-01"
    assert len(c["fit"]) == 12


def test_trend_needs_enough_periods():
    df = pd.DataFrame({"date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]), "v": [1, 2, 3, 4]})
    with pytest.raises(ValueError, match="at least 4"):
        analysis.trend_report(df, "date", "v", "month")


def test_consistency_issues():
    df = pd.DataFrame({"region": ["North", "north ", "South", "South", "South"] * 4,
                       "amount": [10, 12, 11, 13, 12] * 3 + [10, 12, 11, 13, -50]})
    df = pd.concat([df, df.iloc[[0]]])  # one exact duplicate
    types = {i["type"] for i in analysis.consistency_report(df)["issues"]}
    assert {"duplicate_rows", "category_spelling_variants", "unexpected_negative_values"} <= types


def test_compare_finds_key_and_orphans():
    a = pd.DataFrame({"customer_id": [1, 2, 3, 4, 5], "x": list("abcde")})
    b = pd.DataFrame({"Customer_ID": [1, 2, 3, 9], "y": list("wxyz")})
    rep, chart = analysis.compare_report(a, b, "a.csv", "b.csv")
    best = rep["candidate_keys"][0]
    assert best["same_name"] and best["matched_values"] == 3 and best["only_in_a"] == 2 and best["only_in_b"] == 1
    assert chart["matched"] == 3


def test_charts_are_json_and_template_free(sales):
    report, c = analysis.anomaly_report(sales)
    fig = charts.anomaly_scatter(c["values"], c["mask"], c["column"])
    json.dumps(fig)
    assert "template" not in fig["figure"]["layout"]
    assert len(fig["figure"]["data"]) == 2 and len(fig["figure"]["data"][1]["x"]) >= 1


def test_investigation_tool_adds_chart(sales, tmp_path):
    path = tmp_path / "sales.csv"
    sales.to_csv(path, index=False)
    ds = [{"filename": "sales.csv", "path": str(path), "sheets": [{"name": "data", "rows": 200, "columns": list(sales.columns)}]}]
    sink = []
    tool = next(t for t in make_investigation_tools(ds, sink) if t.name == "find_anomalies")
    out = json.loads(tool.invoke({"dataset": "sales.csv", "columns": "Amount"}))
    assert out["top_anomalies"][0]["row_number"] == 52 and len(sink) == 1


def test_graph_runs_investigation_agent(monkeypatch, sales, tmp_path):
    path = tmp_path / "sales.csv"
    sales.to_csv(path, index=False)
    ds = [{"filename": "sales.csv", "path": str(path), "sheets": [{"name": "data", "rows": 200, "columns": list(sales.columns)}]}]
    plan = {"objective": "find outliers", "steps": [{"agent": "investigate", "task": "find anomalies in amount"}]}
    fake = FakeLLM([
        AIMessage(content=json.dumps(plan)),
        AIMessage(content="", tool_calls=[{"name": "find_anomalies", "id": "1", "args": {"dataset": "sales.csv"}}]),
        AIMessage(content="Row 52 has amount 900."),
        AIMessage(content="Row 52 is a clear outlier [I1]."),
        AIMessage(content=json.dumps({"claims": [{"claim": "ok", "verdict": "supported", "evidence": [], "note": "matches"}]})),
    ])
    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: fake)
    result = build_graph().invoke({"question": "any anomalies?", "history": [], "file_ids": None, "datasets": ds,
                                   "documents": [], "logs": [], "evidence": [], "charts": []})
    assert [e["id"] for e in result["evidence"]] == ["I1"]
    assert result["charts"][0]["title"].startswith("Anomalies in")
    agents = [l["agent"] for l in result["logs"]]
    assert "investigate" in agents and "data" not in agents  # data agent skipped
    assert "[I1]" in result["answer"]


def test_trend_is_robust_to_extreme_periods():
    dates = pd.date_range("2024-01-01", periods=12, freq="MS")
    df = pd.DataFrame({"date": dates, "v": [100 + 15 * i for i in range(12)]})
    df.loc[2, "v"] = 5000                      # one huge early outlier would flip a least-squares fit to "falling"
    rep, _ = analysis.trend_report(df, "date", "v")
    assert rep["direction"] == "rising" and rep["rank_correlation"] > 0.5


def test_flat_series_has_no_trend():
    df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=8, freq="MS"), "v": [10, 11, 10, 9, 10, 11, 10, 9]})
    assert analysis.trend_report(df, "date", "v")[0]["direction"] == "no clear trend"
