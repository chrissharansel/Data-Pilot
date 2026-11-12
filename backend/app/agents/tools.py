"""Pandas tools for the Data Agent.

The model never writes code. It picks from a small set of typed, read-only operations, so results are
exact and safe to run. Tools return JSON strings; errors are returned as {"error": ...} so the agent can retry.
"""
import json
import os
from functools import lru_cache

import numpy as np
import pandas as pd
from langchain_core.tools import tool

MAX_CHARS = 3000
NUMERIC_AGGS = {"sum", "mean", "median", "min", "max", "std"}
ALL_AGGS = NUMERIC_AGGS | {"count", "nunique"}


@lru_cache(maxsize=16)
def _load(path: str, sheet: str, mtime: float) -> pd.DataFrame:  # mtime busts the cache if the file changes
    if path.lower().endswith(".csv"):
        return pd.read_csv(path, encoding_errors="replace")
    return pd.read_excel(path, sheet_name=sheet)


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return None if np.isnan(v) else round(float(v), 4)
    return v


def _out(obj) -> str:
    s = json.dumps(obj, default=str)
    return s if len(s) <= MAX_CHARS else s[:MAX_CHARS] + '..."truncated"'


def _records(df: pd.DataFrame, limit: int) -> list[dict]:
    sub = df.head(limit).astype(object)
    return sub.where(sub.notna(), None).to_dict("records")


def catalog_text(datasets: list[dict], documents: list[dict]) -> str:
    lines = []
    for d in datasets:
        for s in d["sheets"]:
            cols = ", ".join(s["columns"][:40])
            lines.append(f'- dataset "{d["filename"]}" sheet "{s["name"]}" ({s["rows"]} rows): {cols}')
    for d in documents:
        lines.append(f'- document "{d["filename"]}"')
    return "\n".join(lines) or "(no files)"


def resolve_frame(datasets: list[dict], dataset: str, sheet: str = ""):
    key = dataset.strip().lower()
    d = next((x for x in datasets if x["filename"].lower() == key), None) \
        or next((x for x in datasets if key and key in x["filename"].lower()), None)
    if not d:
        raise ValueError(f"Unknown dataset '{dataset}'. Available: {[x['filename'] for x in datasets]}")
    names = [s["name"] for s in d["sheets"]]
    sh = sheet if sheet in names else names[0]
    return d["filename"], sh, _load(d["path"], sh, os.path.getmtime(d["path"]))


def resolve_col(df: pd.DataFrame, name: str):
    for c in df.columns:
        if str(c).lower() == name.strip().lower():
            return c
    raise ValueError(f"Unknown column '{name}'. Columns: {[str(c) for c in df.columns]}")


def make_tools(datasets: list[dict]) -> list:
    def frame(dataset: str, sheet: str):
        return resolve_frame(datasets, dataset, sheet)

    col = resolve_col

    @tool
    def describe_columns(dataset: str, sheet: str = "") -> str:
        """Show each column's type, missing count, unique count and (for numbers) min/mean/max. Use this first to learn a dataset."""
        name, sh, df = frame(dataset, sheet)
        cols = []
        for c in df.columns:
            item = {"column": str(c), "dtype": str(df[c].dtype), "missing": int(df[c].isna().sum()), "unique": int(df[c].nunique())}
            if pd.api.types.is_numeric_dtype(df[c]):
                item.update(min=_num(df[c].min()), mean=_num(df[c].mean()), max=_num(df[c].max()))
            cols.append(item)
        return _out({"dataset": name, "sheet": sh, "rows": len(df), "columns": cols})

    @tool
    def aggregate(dataset: str, column: str, agg: str, group_by: str = "", top: int = 10, sheet: str = "") -> str:
        """Compute sum, mean, median, min, max, std, count or nunique of a column, optionally grouped by another column (largest groups first)."""
        agg = agg.strip().lower()
        if agg not in ALL_AGGS:
            raise ValueError(f"agg must be one of {sorted(ALL_AGGS)}")
        name, sh, df = frame(dataset, sheet)
        vcol = col(df, column)
        vals = pd.to_numeric(df[vcol], errors="coerce") if agg in NUMERIC_AGGS else df[vcol]
        if group_by:
            gcol = col(df, group_by)
            res = getattr(vals.groupby(df[gcol]), agg)().sort_values(ascending=False).head(top)
            return _out({"dataset": name, "operation": f"{agg}({vcol}) by {gcol}", "groups_total": int(df[gcol].nunique()),
                         "result": {str(k): _num(v) for k, v in res.items()}})
        return _out({"dataset": name, "operation": f"{agg}({vcol})", "result": _num(getattr(vals, agg)())})

    @tool
    def filter_rows(dataset: str, column: str, operator: str, value: str, limit: int = 10, sheet: str = "") -> str:
        """Count and sample rows where column <operator> value. operator is one of ==, !=, >, <, >=, <=, contains."""
        name, sh, df = frame(dataset, sheet)
        c = col(df, column)
        s = df[c]
        if operator == "contains":
            mask = s.astype(str).str.contains(value, case=False, regex=False, na=False)
        else:
            v = pd.to_numeric(value, errors="coerce") if pd.api.types.is_numeric_dtype(s) else value
            if pd.isna(v):
                raise ValueError(f"'{value}' is not a number but column '{c}' is numeric")
            ops = {"==": s == v, "!=": s != v, ">": s > v, "<": s < v, ">=": s >= v, "<=": s <= v}
            if operator not in ops:
                raise ValueError("operator must be one of ==, !=, >, <, >=, <=, contains")
            mask = ops[operator]
        return _out({"dataset": name, "filter": f"{c} {operator} {value}", "matching_rows": int(mask.sum()),
                     "total_rows": len(df), "sample": _records(df[mask], limit)})

    @tool
    def top_n(dataset: str, column: str, n: int = 5, ascending: bool = False, sheet: str = "") -> str:
        """Return the rows with the largest (or smallest, if ascending=true) values in a numeric column."""
        name, sh, df = frame(dataset, sheet)
        c = col(df, column)
        order = pd.to_numeric(df[c], errors="coerce").sort_values(ascending=ascending).head(n).index
        return _out({"dataset": name, "operation": f"{'bottom' if ascending else 'top'} {n} by {c}", "rows": _records(df.loc[order], n)})

    @tool
    def missing_values(dataset: str, sheet: str = "") -> str:
        """List columns that contain missing values with counts and percentages, and the number of fully duplicated rows."""
        name, sh, df = frame(dataset, sheet)
        miss = df.isna().sum()
        return _out({"dataset": name, "rows": len(df), "duplicate_rows": int(df.duplicated().sum()),
                     "missing": {str(c): {"count": int(n), "percent": round(100 * n / max(len(df), 1), 2)} for c, n in miss.items() if n}})

    return [describe_columns, aggregate, filter_rows, top_n, missing_values]
