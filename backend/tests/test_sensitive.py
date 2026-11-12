import json

from app.agents import sensitive as sv


def test_name_tokens_avoid_false_positives():
    assert sv.is_sensitive_name("customer_email") and sv.is_sensitive_name("Salary") and sv.is_sensitive_name("phoneNumber")
    assert not sv.is_sensitive_name("scorecard") and not sv.is_sensitive_name("company") and not sv.is_sensitive_name("amount")


def test_value_patterns_and_luhn():
    assert sv.pattern_hits("mail bob@example.com now") == {"email"}
    assert "card" in sv.pattern_hits("card 4111 1111 1111 1111")          # valid Luhn
    assert "card" not in sv.pattern_hits("order 1234 5678 9012 3456")      # fails Luhn
    assert "ssn" in sv.pattern_hits("123-45-6789") and "phone" in sv.pattern_hits("+91 98765 43210")


def test_row_level_columns_flagged_but_aggregates_are_not():
    rows = json.dumps({"sample": [{"customer_email": "a@x.com", "amount": 5}]})
    assert sv.sensitive_columns("filter_rows", rows) == {"customer_email"}
    agg = json.dumps({"operation": "sum(salary) by dept", "result": {"Card": 3, "Phone": 9}})
    assert sv.sensitive_columns("aggregate", agg) == set()                  # statistics, and 'Phone' is just a category
    stats = json.dumps({"per_column": {"salary": {"zscore_outliers": 1}}})
    assert sv.sensitive_columns("find_anomalies", stats) == set()          # nested stats, not a row value


def test_masking_works_even_on_truncated_json():
    truncated = '{"sample": [{"customer_email": "a@x.com", "salary": 90000, "amount": 5}, {"customer_email": "b@x.'
    out = sv.mask_result("filter_rows", truncated)
    assert "a@x.com" not in out and "90000" not in out and '"amount": 5' in out


def _fixture():
    ev = [{"id": "D1", "tool": "filter_rows", "args": {"value": "a@x.com"}, "result": '{"sample": [{"email": "a@x.com", "amount": 5}]}'},
          {"id": "D2", "tool": "aggregate", "args": {}, "result": '{"result": 5}'}]
    src = [{"n": 1, "filename": "p.txt", "location": "text", "snippet": "write to hr@corp.com"}, {"n": 2, "filename": "p.txt", "location": "text", "snippet": "fine"}]
    ch = [{"id": "IC1", "title": "Anomalies in salary", "figure": {}}, {"id": "IC2", "title": "Anomalies in amount", "figure": {}}]
    return ev, src, ch


def test_scan_finds_evidence_sources_and_sensitive_charts():
    ev, src, ch = _fixture()
    kinds = {(f["kind"], f["id"]) for f in sv.scan(ev, src, ch)}
    assert kinds == {("evidence", "D1"), ("source", "1"), ("chart", "IC1")}


def test_apply_mask_and_reject():
    ev, src, ch = _fixture()
    f = sv.scan(ev, src, ch)
    e2, s2, c2 = sv.apply("mask", f, ev, src, ch)
    assert "a@x.com" not in json.dumps([e2, s2]) and [c["id"] for c in c2] == ["IC2"]
    assert [e["id"] for e in e2] == ["D1", "D2"]
    e3, s3, c3 = sv.apply("reject", f, ev, src, ch)
    assert [e["id"] for e in e3] == ["D2"] and [s["n"] for s in s3] == [2] and [c["id"] for c in c3] == ["IC2"]
    e4, _, c4 = sv.apply("approve", f, ev, src, ch)
    assert e4 == ev and len(c4) == 2
