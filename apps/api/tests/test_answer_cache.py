import io
import json

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app import llm
from app.answer import PROMPT_VERSION
from app.main import app, llm_dependency
from tests.helpers import new_tenant

c = TestClient(app)


class Counting:
    def __init__(self):
        self.calls = 0

    def complete(self, system, prompt):
        self.calls += 1
        return json.dumps({"claims": []})  # no claims: a not_found answer, which is cacheable


def upload(h, name):
    wb = Workbook()
    wb.active["A1"] = name
    b = io.BytesIO()
    wb.save(b)
    r = c.post("/documents", files={"file": (f"{name}.xlsx", b.getvalue(), "x")}, data={"deal": "Cache"}, headers=h)
    assert r.status_code in (200, 201), r.text


def test_repeat_question_is_served_from_cache_until_a_document_changes():
    h = new_tenant(c, "answer-cache")
    upload(h, "revenue first")
    fake = Counting()
    app.dependency_overrides[llm_dependency] = lambda: fake
    try:
        first = c.post("/ask", json={"question": "what is revenue"}, headers=h).json()
        assert first["cached"] is False and first["prompt_version"] == PROMPT_VERSION
        second = c.post("/ask", json={"question": "what is revenue"}, headers=h).json()
        assert second["cached"] is True and fake.calls == 1  # the model was not called again
        upload(h, "revenue second")  # the visible set of documents changed: a new key
        third = c.post("/ask", json={"question": "what is revenue"}, headers=h).json()
        assert third["cached"] is False and fake.calls == 2
    finally:
        app.dependency_overrides.pop(llm_dependency)


class Broken:
    def complete(self, system, prompt):
        raise ConnectionError("provider down")


class Working:
    def complete(self, system, prompt):
        return "from the second provider"


def test_fallback_is_used_only_when_the_primary_fails():
    assert llm.FallbackLLM(Broken(), lambda: Working()).complete("s", "p") == "from the second provider"
    assert llm.FallbackLLM(Working(), lambda: Broken()).complete("s", "p") == "from the second provider"


def test_fallback_is_not_used_when_the_tenant_is_over_its_allowance():
    class Capped:
        def complete(self, system, prompt):
            raise llm.LLMCapExceeded("used up")
    try:
        llm.FallbackLLM(Capped(), lambda: Working()).complete("s", "p")
        raise AssertionError("expected the cap to stop the call")
    except llm.LLMCapExceeded:
        pass


class Fabricating:
    id = "llamacpp:test-model.gguf"

    def complete(self, system, prompt):
        claim = {"text": "Revenue was 999 million", "doc_id": "missing", "page": 1, "quote": "Revenue 999 million"}
        return json.dumps({"claims": [claim]})


def test_cache_key_changes_with_the_provider_and_model():
    from app import answer_cache

    base = answer_cache.key("q", None, [], "anthropic:a")
    assert base == answer_cache.key("q", None, [], "anthropic:a")
    assert base != answer_cache.key("q", None, [], "anthropic:b")
    assert base != answer_cache.key("q", None, [], "llamacpp:a")


def test_fallback_answer_goes_through_the_citation_gate_and_is_stamped_with_the_model_that_wrote_it():
    h = new_tenant(c, "fallback-gate")
    upload(h, "revenue fallback")
    app.dependency_overrides[llm_dependency] = lambda: llm.FallbackLLM(
        Broken(), lambda: Fabricating(), secondary_id="llamacpp:test-model.gguf")
    try:
        body = c.post("/ask", json={"question": "what is revenue"}, headers=h).json()
    finally:
        app.dependency_overrides.pop(llm_dependency)
    assert body["status"] == "not_found" and body["claims"] == []  # the unverifiable claim was rejected
    assert len(body["rejected"]) == 1 and body["rejected"][0]["reason"]
    assert body["model"] == "llamacpp:test-model.gguf"
