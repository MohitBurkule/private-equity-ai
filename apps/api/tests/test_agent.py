import io
import json

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app import agent as ag
from app.main import app, llm_dependency, optional_llm_dependency
from tests.helpers import new_tenant

c = TestClient(app)


class Script:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, system, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def upload(h, rows):
    wb = Workbook()
    for i, t in enumerate(rows, 1):
        wb.active.cell(i, 1, t)
    b = io.BytesIO()
    wb.save(b)
    return c.post("/documents", files={"file": ("p.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]


def agent(h, llm, goal="when does the board meet"):
    app.dependency_overrides[llm_dependency] = lambda: llm
    try:
        return c.post("/agent/run", headers=h, json={"goal": goal}).json()
    finally:
        app.dependency_overrides.pop(llm_dependency)


def test_agent_searches_then_answers_with_verified_claims_only():
    h = new_tenant(c, "ag1")
    doc = upload(h, ["Board meets quarterly", "Partner sign-off above 50 million"])
    llm = Script([
        json.dumps({"tool": "search_documents", "args": {"query": "board meets"}}),
        json.dumps({"final": [
            {"text": "Board meets quarterly", "doc_id": doc, "page": 1, "quote": "Board meets quarterly"},
            {"text": "Board meets monthly", "doc_id": doc, "page": 1, "quote": "Board meets monthly"}]}),
    ])
    r = agent(h, llm)
    assert r["status"] == "done" and r["result"]["status"] == "answered"
    assert [x["text"] for x in r["result"]["claims"]] == ["Board meets quarterly"]
    assert r["result"]["rejected"][0]["reason"] == "quote not found on cited page"
    assert "<tool_result" in llm.prompts[1] and doc in llm.prompts[1]
    assert c.get("/agent/runs", headers=h).json()[0]["id"] == r["id"]


def test_agent_bad_tool_unknown_and_step_limit_and_isolation():
    h = new_tenant(c, "ag2")
    llm = Script([json.dumps({"tool": "drop_db", "args": {}}), "not json"])
    r = agent(h, llm)
    assert r["status"] == "failed" and r["steps"][0]["error"].startswith("unknown tool")
    loop = Script([json.dumps({"tool": "list_deals", "args": {}})] * 3)
    app.dependency_overrides[llm_dependency] = lambda: loop
    try:
        r = c.post("/agent/run", headers=h, json={"goal": "x", "max_steps": 2}).json()
    finally:
        app.dependency_overrides.pop(llm_dependency)
    assert r["status"] == "failed" and "2 steps" in r["error"]
    assert c.get("/agent/runs", headers=new_tenant(c, "ag3")).json() == []


def test_workflow_refs_and_failure_and_write_gate():
    @ag.register_tool("test_echo", "echo", {"x": "any"})
    def echo(ctx, x):
        return {"v": x}

    @ag.register_tool("test_write", "w", {}, writes=True)
    def w(ctx):
        return {}

    ag.register_workflow(ag.Workflow("test_wf", "t", {"msg": "text"}, (
        ag.Step("a", "test_echo", {"x": "$input.msg"}),
        ag.Step("b", "test_echo", {"x": ["$a.v", "$a.v"]}))))
    ag.register_workflow(ag.Workflow("test_bad", "t", {}, (ag.Step("a", "test_echo", {"x": "$nope.z"}),)))
    ag.register_workflow(ag.Workflow("test_w", "t", {}, (ag.Step("a", "test_write"),)))
    h = new_tenant(c, "ag4")
    r = c.post("/agent/workflows/test_wf/run", headers=h, json={"inputs": {"msg": "hi"}}).json()
    assert r["status"] == "done" and r["result"] == {"v": ["hi", "hi"]}
    assert c.post("/agent/workflows/test_wf/run", headers=h, json={}).status_code == 422
    assert c.post("/agent/workflows/nope/run", headers=h, json={}).status_code == 404
    assert c.post("/agent/workflows/test_bad/run", headers=h, json={}).json()["status"] == "failed"
    assert c.post("/agent/workflows/test_w/run", headers=h, json={}).json()["status"] == "done"
    assert "test_echo" in [t["name"] for t in c.get("/agent/tools", headers=h).json()]


def test_profile_tool_returns_accepted_only():
    h = new_tenant(c, "ag5")
    ag.register_workflow(ag.Workflow("test_prof", "t", {}, (ag.Step("p", "get_firm_profile"),)))
    assert c.post("/agent/workflows/test_prof/run", headers=h, json={}).json()["result"] == {}


def test_build_firm_profile_workflow_extracts_then_reports_gaps():
    h = new_tenant(c, "ag6")
    doc = upload(h, ["Board meets quarterly"])
    llm = Script([json.dumps({"values": [
        {"key": "board_meeting_frequency", "value": "quarterly", "page": 1, "quote": "Board meets quarterly"}]})])
    app.dependency_overrides[optional_llm_dependency] = lambda: llm
    try:
        r = c.post("/agent/workflows/build_firm_profile/run", headers=h, json={"inputs": {"document_id": doc}}).json()
    finally:
        app.dependency_overrides.pop(optional_llm_dependency)
    assert r["status"] == "done", r
    assert len(r["steps"][0]["output"]["saved"]) == 1
    assert "board_meeting_frequency" in r["result"]["missing"]  # pending is not known until accepted
