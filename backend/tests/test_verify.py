import json

from langchain_core.messages import AIMessage

from app.agents import nodes, verify
from app.agents.graph import build_graph

from .test_agents import FakeLLM, datasets  # noqa: F401  (datasets is a pytest fixture)

EVIDENCE = [{"id": "D1", "tool": "aggregate", "args": {"column": "amount"},
             "result": '{"result": {"S": 5110.4, "N": 300}, "share": 25.3}'}]
SOURCES = [{"n": 1, "filename": "p.pdf", "location": "page 1", "snippet": "Orders over 500 need approval."}]


def check(answer, question="q"):
    return verify.check_answer(answer, question, EVIDENCE, SOURCES)


def test_valid_answer_passes():
    det = check("South totals 5,110 [D1]. Policy needs approval over 500 [1].")
    assert det["invalid"] == [] and det["ungrounded"] == []
    assert verify.summarize(det)["status"] == "verified"


def test_invalid_citation_and_invented_number_are_caught():
    det = check("South totals 7777 [D9].")
    assert det["invalid"] == ["D9"] and det["ungrounded"] == ["7777"]
    v = verify.summarize(det)
    assert v["status"] == "unverified" and verify.needs_revision(v)


def test_percent_and_fraction_forms_match():
    assert check("The share is 25.3% [D1].")["ungrounded"] == []
    assert check("The share is 99.9% [D1].")["ungrounded"] == ["99.9%"]


def test_small_integers_and_question_numbers_are_ignored():
    assert check("Top 3 regions matter [D1].")["ungrounded"] == []
    assert check("Threshold 4200 was used [D1].", question="why 4200?")["ungrounded"] == []


def test_uncited_numeric_sentence_is_partial_not_verified():
    v = verify.summarize(check("South totals 5110."))
    assert v["claims"][0]["verdict"] == "partial" and v["status"] != "verified"
    assert any("no citations" in i for i in v["issues"])


def test_llm_supported_is_downgraded_when_number_is_ungrounded():
    det = check("South totals 7777 [D1].")
    v = verify.summarize(det, [{"claim": "South totals 7777", "verdict": "supported", "evidence": ["D1"], "note": ""}])
    assert v["claims"][0]["verdict"] == "partial"


def test_parse_llm_claims_sanitises():
    out = verify.parse_llm_claims({"claims": [{"claim": "x", "verdict": "weird", "evidence": ["D1", "Z9"]}, "junk"]}, {"D1"})
    assert out == [{"claim": "x", "verdict": "partial", "evidence": ["D1"], "note": ""}]


def test_verifier_skips_when_no_evidence():
    out = nodes.verifier_node({"question": "q", "answer": "none", "evidence": [], "sources": []})
    assert out["verification"]["status"] == "not_applicable"


def test_revision_loop_fixes_invented_number(monkeypatch, datasets):  # noqa: F811
    plan = {"objective": "o", "steps": [{"agent": "data", "task": "sum by region"}]}
    fake = FakeLLM([
        AIMessage(content=json.dumps(plan)),
        AIMessage(content="", tool_calls=[{"name": "aggregate", "id": "1", "args": {"dataset": "orders.csv", "column": "amount", "agg": "sum", "group_by": "region"}}]),
        AIMessage(content="South 5110, North 300."),
        AIMessage(content="The total is 7777 [D1]."),                       # writer, first attempt: invented number
        AIMessage(content="South totals 5110 [D1]."),                         # writer, after feedback
        AIMessage(content=json.dumps({"claims": [{"claim": "South totals 5110", "verdict": "supported", "evidence": ["D1"], "note": "ok"}]})),
    ])
    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: fake)
    result = build_graph().invoke({"question": "totals?", "history": [], "file_ids": None, "datasets": datasets,
                                   "documents": [], "logs": [], "evidence": [], "charts": []})
    assert result["answer"] == "South totals 5110 [D1]."
    assert result["verification"]["status"] == "verified" and result["revisions"] == 1
    actions = [l["action"] for l in result["logs"]]
    assert "Requested revision" in actions and "Revised answer after verification" in actions
    assert not fake.script
