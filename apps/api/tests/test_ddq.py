import io
import json

from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.main as m
from tests.helpers import new_tenant

c = TestClient(m.app)


def xlsx():
    wb = Workbook()
    wb.active["A1"], wb.active["B1"] = "Revenue", 1234
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


class Scripted:
    def __init__(self, doc):
        self.doc, self.n = doc, 0

    def complete(self, system, prompt):
        self.n += 1
        if "boom" in prompt:
            raise RuntimeError("llm down")
        if "revenue" in prompt.lower() and "unrelated" not in prompt:
            return json.dumps({"claims": [{"text": "Revenue was 1,234", "doc_id": self.doc, "page": 1,
                                           "quote": "Sheet!B1: 1,234"}]})
        return json.dumps({"claims": []})


def test_ddq_batch_flags_unanswered_and_isolates_errors():
    h = new_tenant(c, "ddq1")
    doc = c.post("/documents", files={"file": ("a.xlsx", xlsx(), "x")}, headers=h).json()["id"]
    m.app.dependency_overrides[m.llm_dependency] = lambda: Scripted(doc)
    try:
        r = c.post("/ddq", headers=h, json={"questions": ["What was revenue?", "boom revenue?", "", "unrelated thing"]})
        assert r.status_code == 200
        items = r.json()["items"]
        # This scripted quote has no row label on its line, so the label gate abstains rather than trust a
        # number whose row is unproven. Real xlsx lines carry "| row: <label>" (see test_xlsx_labels.py).
        assert [i["status"] for i in items] == ["not_found", "error", "skipped", "not_found"]
        assert [i["needs_human"] for i in items] == [True, True, True, True]
        assert c.post("/ddq", headers=h, json={"questions": []}).status_code == 422
        assert c.post("/ddq", headers=h, json={"questions": ["q"] * 201}).status_code == 422
    finally:
        m.app.dependency_overrides.clear()


def test_ddq_with_empty_corpus_marks_every_question_for_a_human():
    h = new_tenant(c, "ddq2")
    m.app.dependency_overrides[m.llm_dependency] = lambda: Scripted("none")
    try:
        items = c.post("/ddq", headers=h, json={"questions": ["What was revenue?", "What is the fund size?"]}).json()["items"]
        assert [i["status"] for i in items] == ["not_found", "not_found"]
        assert all(i["needs_human"] and i["claims"] == [] for i in items)
    finally:
        m.app.dependency_overrides.clear()
