import pytest
from fastapi.testclient import TestClient

from app import llm
from app.audit import (
    AuditEvent,  # noqa: F401  (keeps the mapper loaded for the shared engine)
)
from app.main import SessionLocal, app
from app.models import LlmUsage
from app.rls import bind_tenant

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}


class Echo:
    def complete(self, system: str, prompt: str) -> str:
        return "answer"


def new_tenant_id(name: str) -> str:
    return c.post("/admin/tenants", json={"name": name}, headers=ADMIN).json()["tenant_id"]


def test_cap_refuses_once_the_day_is_used_up(monkeypatch):
    monkeypatch.setenv("LLM_DAILY_CHAR_CAP", "50")
    tid = new_tenant_id("llm-cap")
    with SessionLocal() as s:
        bind_tenant(s, tid)
        wrapped = llm.CappedLLM(Echo(), s, tid)
        assert wrapped.complete("sys", "x" * 20) == "answer"  # 3 + 20 + 6 = 29 characters
        with pytest.raises(llm.LLMCapExceeded):
            wrapped.complete("sys", "x" * 40)  # 29 + 43 is over 50


def test_no_cap_by_default_but_usage_is_recorded(monkeypatch):
    monkeypatch.delenv("LLM_DAILY_CHAR_CAP", raising=False)
    tid = new_tenant_id("llm-usage")
    with SessionLocal() as s:
        bind_tenant(s, tid)
        wrapped = llm.CappedLLM(Echo(), s, tid)
        for _ in range(3):
            wrapped.complete("sys", "x" * 100)
        row = s.query(LlmUsage).filter_by(tenant_id=tid).one()
        assert row.calls == 3 and row.chars == 3 * (3 + 100 + 6)


def test_no_provider_still_refuses_with_a_tenant(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    with SessionLocal() as s, pytest.raises(llm.NoLLMConfigured):
        llm.get_llm(s, "t")
