"""Plotly figure builders. Figures are returned as plain JSON dicts; the React app renders them with plotly.js."""
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go

BASE, BAD, MUTED, FIT = "#3b5bdb", "#d64545", "#a9b3cf", "#e8a33d"


def _pack(fig: go.Figure, title: str, xtitle: str = "", ytitle: str = "") -> dict:
    fig.update_layout(title_text=title, xaxis_title=xtitle or None, yaxis_title=ytitle or None)
    d = json.loads(fig.to_json())
    d.get("layout", {}).pop("template", None)
    return {"title": title, "figure": d}


def anomaly_scatter(values: pd.Series, mask: pd.Series, column: str) -> dict:
    v = pd.to_numeric(values, errors="coerce")
    ok = v.notna()
    pos = pd.Series(np.arange(len(v)) + 2, index=v.index)  # spreadsheet row numbers
    normal, bad = ok & ~mask, ok & mask
    step = max(1, int(normal.sum() // 1500))  # keep the chart light: thin the normal points, never the anomalies
    n_idx = v.index[normal][::step]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=pos[n_idx].tolist(), y=v[n_idx].tolist(), mode="markers", name="Normal",
                             marker=dict(color=MUTED, size=6)))
    fig.add_trace(go.Scatter(x=pos[bad].tolist(), y=v[bad].tolist(), mode="markers", name="Flagged",
                             marker=dict(color=BAD, size=10, line=dict(color="white", width=1)),
                             hovertemplate="row %{x}<br>value %{y}<extra></extra>"))
    return _pack(fig, f"Anomalies in {column}", "Row number", column)


def trend_chart(series: pd.Series, fit: pd.Series, value_label: str) -> dict:
    x = [i.strftime("%Y-%m-%d") for i in series.index]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=series.tolist(), mode="lines+markers", name="Actual", line=dict(color=BASE)))
    fig.add_trace(go.Scatter(x=x, y=fit.tolist(), mode="lines", name="Trend", line=dict(color=FIT, dash="dash")))
    return _pack(fig, f"Trend of {value_label}", "", value_label)


def match_chart(matched: int, only_a: int, only_b: int, name_a: str, name_b: str, label: str) -> dict:
    fig = go.Figure(go.Bar(x=[matched, only_a, only_b], y=["In both", f"Only in {name_a}", f"Only in {name_b}"],
                           orientation="h", marker_color=[BASE, BAD, BAD]))
    fig.update_layout(showlegend=False)
    return _pack(fig, f"Key overlap: {label}", "Distinct key values", "")


def bar_from_aggregate(result_json: str) -> dict | None:
    """Turn a grouped Data Agent result into a bar chart; returns None if it isn't chartable."""
    try:
        r = json.loads(result_json)
        data = r["result"]
        if not isinstance(data, dict) or len(data) < 2:
            return None
        labels, values = list(data.keys()), list(data.values())
        if any(v is None for v in values):
            return None
        fig = go.Figure(go.Bar(x=labels, y=values, marker_color=BASE))
        fig.update_layout(showlegend=False)
        return _pack(fig, f"{r['operation']}", "", "")
    except Exception:
        return None
