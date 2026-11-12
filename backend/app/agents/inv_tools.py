"""Tools for the Investigation Agent. Like the Data Agent's tools they are typed and read-only; they also
drop Plotly charts into a shared list so the UI can show them next to the answer."""
from langchain_core.tools import tool

from . import analysis, charts
from .tools import _out, resolve_col, resolve_frame


def make_investigation_tools(datasets: list[dict], sink: list) -> list:
    def add_chart(c: dict):
        sink.append({"id": f"IC{len(sink) + 1}", **c})

    @tool
    def find_anomalies(dataset: str, columns: str = "", sheet: str = "") -> str:
        """Find statistical outliers in numeric columns using z-score (>3), IQR fences and Isolation Forest. Optional columns: comma-separated names. Returns spreadsheet row numbers."""
        name, sh, df = resolve_frame(datasets, dataset, sheet)
        only = [str(resolve_col(df, c)) for c in columns.split(",") if c.strip()] or None
        report, chart = analysis.anomaly_report(df, only)
        if chart:
            add_chart(charts.anomaly_scatter(chart["values"], chart["mask"], chart["column"]))
        return _out({"dataset": name, **report})

    @tool
    def analyze_trend(dataset: str, date_column: str, value_column: str, period: str = "month", agg: str = "sum", sheet: str = "") -> str:
        """Analyse how a numeric column changes over time. period is day, week, month, quarter or year; agg is sum, mean, median, min, max or count."""
        name, sh, df = resolve_frame(datasets, dataset, sheet)
        dcol, vcol = resolve_col(df, date_column), resolve_col(df, value_column)
        report, c = analysis.trend_report(df, dcol, vcol, period, agg)
        add_chart(charts.trend_chart(c["series"], c["fit"], f"{agg}({vcol}) per {period}"))
        return _out({"dataset": name, **report})

    @tool
    def check_consistency(dataset: str, sheet: str = "") -> str:
        """Check a dataset for data-quality problems: duplicate rows, unexpected negatives, spelling variants of the same category, mixed numbers and text, high missing rates."""
        name, sh, df = resolve_frame(datasets, dataset, sheet)
        return _out({"dataset": name, **analysis.consistency_report(df)})

    @tool
    def compare_datasets(dataset_a: str, dataset_b: str, sheet_a: str = "", sheet_b: str = "") -> str:
        """Find columns that link two datasets (shared keys such as customer or order ids) and report values present in one but missing from the other."""
        na, _, a = resolve_frame(datasets, dataset_a, sheet_a)
        nb, _, b = resolve_frame(datasets, dataset_b, sheet_b)
        report, chart = analysis.compare_report(a, b, na, nb)
        if chart:
            add_chart(charts.match_chart(chart["matched"], chart["only_a"], chart["only_b"], na, nb, chart["label"]))
        return _out(report)

    return [find_anomalies, analyze_trend, check_consistency, compare_datasets]
