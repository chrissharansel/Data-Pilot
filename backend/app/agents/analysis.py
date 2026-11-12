"""Statistical analysis used by the Investigation Agent. Pure functions: no LLM, easy to test."""
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

PERIODS = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}
AGGS = {"sum", "mean", "median", "min", "max", "count"}


def val(v):
    """Make numpy / pandas scalars JSON-safe."""
    if v is None:
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return None if np.isnan(v) else round(float(v), 4)
    return v if isinstance(v, str) else str(v)


def numeric_columns(df: pd.DataFrame, only: list[str] | None = None) -> list:
    wanted = {o.lower() for o in only} if only else None
    cols = []
    for c in df.columns:
        s = df[c]
        if not pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
            continue
        # skip running-number id columns: they are never "anomalous"
        if pd.api.types.is_integer_dtype(s) and s.is_unique and (s.is_monotonic_increasing or s.is_monotonic_decreasing):
            continue
        if wanted and str(c).lower() not in wanted:
            continue
        cols.append(c)
    return cols


# ---------------- anomalies ----------------
def univariate_outliers(s: pd.Series) -> dict | None:
    x = s.dropna()
    if len(x) < 8 or x.std() == 0:
        return None
    mean, std = x.mean(), x.std()
    z = (s - mean) / std
    q1, q3 = x.quantile(0.25), x.quantile(0.75)
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    iqr_mask = ((s < lo) | (s > hi)) if iqr > 0 else pd.Series(False, index=s.index)
    return {"z": z, "z_mask": (z.abs() > 3).fillna(False), "iqr_mask": iqr_mask.fillna(False),
            "bounds": (lo, hi), "mean": mean, "std": std}


def isolation_scores(df: pd.DataFrame, cols: list, contamination: float = 0.02):
    """Multivariate view: rows that are unusual across several columns together. Flags the ~2% most isolated rows."""
    if len(df) < 20 or not cols:
        return None
    X = df[cols].apply(pd.to_numeric, errors="coerce")
    X = X.fillna(X.median()).fillna(0)
    model = IsolationForest(n_estimators=200, contamination=contamination, random_state=42).fit(X)
    return pd.Series(-model.score_samples(X), index=df.index), pd.Series(model.predict(X) == -1, index=df.index)


def anomaly_report(df: pd.DataFrame, only: list[str] | None = None, top: int = 8):
    cols = numeric_columns(df, only)
    if not cols:
        raise ValueError("No numeric columns to analyse in this dataset.")
    per_col, found, zs, masks = {}, {}, {}, {}
    for c in cols:
        r = univariate_outliers(df[c])
        if r is None:
            continue
        zs[c], masks[c] = r["z"], r["z_mask"] | r["iqr_mask"]
        per_col[str(c)] = {"zscore_outliers": int(r["z_mask"].sum()), "iqr_outliers": int(r["iqr_mask"].sum()),
                           "iqr_normal_range": [val(r["bounds"][0]), val(r["bounds"][1])],
                           "mean": val(r["mean"]), "std": val(r["std"])}
        for i in df.index[r["z_mask"]]:
            found.setdefault(i, {"methods": set(), "cols": set()})["methods"].add("zscore")
            found[i]["cols"].add(c)
        for i in df.index[r["iqr_mask"]]:
            found.setdefault(i, {"methods": set(), "cols": set()})["methods"].add("iqr")
            found[i]["cols"].add(c)

    iso = isolation_scores(df, list(zs) or cols)
    iso_flagged = iso[1] if iso else pd.Series(False, index=df.index)
    if iso:
        for i in df.index[iso[1]]:
            found.setdefault(i, {"methods": set(), "cols": set()})["methods"].add("isolation_forest")

    def rank(i):
        return (len(found[i]["methods"]), float(iso[0][i]) if iso else 0.0)

    rows = []
    for i in sorted(found, key=rank, reverse=True)[:top]:
        show = list(found[i]["cols"]) or sorted(zs, key=lambda c: -abs(zs[c].get(i, 0) or 0))[:3]
        rows.append({"row_number": int(df.index.get_loc(i)) + 2,  # spreadsheet row, header is row 1
                     "flagged_by": sorted(found[i]["methods"]),
                     "values": {str(c): val(df.at[i, c]) for c in list(show)[:4]}})

    report = {"rows_analysed": int(len(df)), "columns_analysed": [str(c) for c in cols], "per_column": per_col,
              "rows_flagged_total": len(found),
              "note": "Isolation Forest flags the 2% most isolated rows, so it always flags a few; trust rows flagged by several methods.",
              "top_anomalies": rows}
    chart = None
    if masks:
        best = max(masks, key=lambda c: int(masks[c].sum()))
        chart = {"column": str(best), "values": df[best], "mask": masks[best] | iso_flagged}
    return report, chart


# ---------------- trends ----------------
def trend_report(df: pd.DataFrame, date_col, value_col, period: str = "month", agg: str = "sum"):
    freq, agg = PERIODS.get(period.lower(), "M"), agg.lower() if agg.lower() in AGGS else "sum"
    d = pd.to_datetime(df[date_col], errors="coerce")
    v = pd.to_numeric(df[value_col], errors="coerce")
    ok = d.notna() & v.notna()
    if ok.sum() < 4:
        raise ValueError(f"Fewer than 4 rows have a valid date in '{date_col}' and a number in '{value_col}'.")
    s = v[ok].groupby(d[ok].dt.to_period(freq)).agg(agg).sort_index()
    if len(s) < 4:
        raise ValueError(f"Only {len(s)} {period} period(s) of data; need at least 4. Try period='day' or 'week'.")
    s.index = s.index.to_timestamp()
    # Robust trend: Theil-Sen slope (median of pairwise slopes) and Spearman rank correlation. Unlike a least-squares
    # fit, a few extreme periods cannot flip the verdict, which matters because this tool is used on data with outliers.
    y = s.values.astype(float)[-1000:]
    x = np.arange(len(y), dtype=float)
    i, j = np.triu_indices(len(y), 1)
    slope = float(np.median((y[j] - y[i]) / (x[j] - x[i])))
    intercept = float(np.median(y - slope * x))
    fit = pd.Series(intercept + slope * np.arange(len(s), dtype=float)[-len(y):], index=s.index[-len(y):])
    rho = pd.Series(y).corr(pd.Series(x), method="spearman")
    rho = 0.0 if pd.isna(rho) else float(rho)
    direction = "no clear trend" if abs(rho) < 0.5 else ("rising" if slope > 0 else "falling")
    pct = s.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    jump = None
    if len(pct):
        k = pct.abs().idxmax()
        jump = {"period": k.strftime("%Y-%m-%d"), "change_pct": round(float(pct[k]) * 100, 1)}
    first, last = float(s.iloc[0]), float(s.iloc[-1])
    report = {"periods_analysed": int(len(s)), "period": period, "aggregation": f"{agg}({value_col})",
              "direction": direction, "rank_correlation": round(rho, 3), "slope_per_period": val(slope),
              "method": "Theil-Sen slope, Spearman rank correlation (robust to outliers)", "first_value": val(first), "last_value": val(last),
              "change_pct_first_to_last": round((last - first) / abs(first) * 100, 1) if first else None,
              "largest_period_jump": jump,
              "series": [{"period": i.strftime("%Y-%m-%d"), "value": val(x_)} for i, x_ in list(s.items())[-36:]]}
    return report, {"series": s, "fit": pd.Series(fit, index=s.index)}


# ---------------- consistency ----------------
def consistency_report(df: pd.DataFrame) -> dict:
    issues = []
    n = len(df)
    dup = df.duplicated(keep="first")
    if dup.any():
        issues.append({"type": "duplicate_rows", "count": int(dup.sum()),
                       "example_row_numbers": [int(df.index.get_loc(i)) + 2 for i in df.index[dup][:5]]})
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            nonnull = s.dropna()
            neg = nonnull < 0
            if neg.any() and (nonnull > 0).mean() >= 0.95:
                issues.append({"type": "unexpected_negative_values", "column": str(c), "count": int(neg.sum()),
                               "example_row_numbers": [int(df.index.get_loc(i)) + 2 for i in nonnull.index[neg][:5]],
                               "why": "column is almost entirely positive"})
        elif pd.api.types.is_string_dtype(s) or s.dtype == object:  # 'str' dtype in newer pandas, object in older
            text = s.dropna().astype(str)
            if text.empty:
                continue
            groups = text.groupby(text.str.strip().str.lower()).agg(lambda x: sorted(set(x)))
            variants = [g for g in groups if len(g) > 1]
            if variants:
                issues.append({"type": "category_spelling_variants", "column": str(c), "groups": len(variants),
                               "examples": variants[:4]})
            share = pd.to_numeric(text, errors="coerce").notna().mean()
            if 0.05 < share < 0.95:
                issues.append({"type": "mixed_numbers_and_text", "column": str(c), "numeric_share_pct": round(share * 100, 1)})
        miss = s.isna().mean()
        if miss > 0.2:
            issues.append({"type": "high_missing_rate", "column": str(c), "missing_pct": round(float(miss) * 100, 1)})
    return {"rows": n, "issue_count": len(issues), "issues": issues[:15]}


# ---------------- cross-dataset ----------------
def _key_set(s: pd.Series) -> set:
    return set(s.dropna().astype(str).str.strip().str.lower())


def compare_report(a: pd.DataFrame, b: pd.DataFrame, name_a: str, name_b: str):
    pairs = []
    for ca in list(a.columns)[:15]:
        if pd.api.types.is_float_dtype(a[ca]):
            continue
        for cb in list(b.columns)[:15]:
            if pd.api.types.is_float_dtype(b[cb]):
                continue
            ka, kb = _key_set(a[ca]), _key_set(b[cb])
            if len(ka) < 2 or len(kb) < 2:
                continue
            overlap = len(ka & kb) / min(len(ka), len(kb))
            same = str(ca).lower() == str(cb).lower()
            if overlap >= 0.3 or same:
                pairs.append((same, overlap, ca, cb, ka, kb))
    if not pairs:
        return {"datasets": [name_a, name_b], "candidate_keys": [],
                "note": "No columns with matching names or overlapping values were found, so the datasets look unrelated."}, None
    pairs.sort(key=lambda p: (p[0], p[1]), reverse=True)
    out = []
    for same, ov, ca, cb, ka, kb in pairs[:4]:
        out.append({"column_a": str(ca), "column_b": str(cb), "same_name": same, "overlap_pct": round(ov * 100, 1),
                    "matched_values": len(ka & kb), "only_in_a": len(ka - kb), "only_in_b": len(kb - ka),
                    "key_unique_in_a": bool(a[ca].dropna().is_unique), "key_unique_in_b": bool(b[cb].dropna().is_unique),
                    "unmatched_examples_a": sorted(ka - kb)[:3], "unmatched_examples_b": sorted(kb - ka)[:3]})
    best = out[0]
    return ({"datasets": [name_a, name_b], "candidate_keys": out},
            {"matched": best["matched_values"], "only_a": best["only_in_a"], "only_b": best["only_in_b"],
             "label": f"{best['column_a']} ↔ {best['column_b']}"})
