"""Data-room checklist: required-document gaps for a deal, raised as one alert per distinct gap."""
from fastapi.testclient import TestClient

import app.main as m
from app.dataroom_check import gaps, parse_required
from app.main import app
from tests.helpers import new_tenant
from tests.test_connectors import fake, gmail_routes

c = TestClient(app)


def test_patterns_match_base_name_case_insensitively_in_any_folder():
    names = ["room/Financials/FY24_Financials.XLSX", "QoE_report.pdf"]
    assert gaps(names, ["*financials*.xlsx", "*qoe*.pdf"]) == []
    assert gaps(names, ["*legal*.pdf", "*qoe*.pdf"]) == ["*legal*.pdf"]
    assert parse_required(" *a*.pdf, ,*b* ") == ["*a*.pdf", "*b*"]


def test_missing_required_document_raises_one_warning_per_gap(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(gmail_routes()))
    h = new_tenant(c, "room-gap")
    body = {"token": "tok", "deal": "atlas", "options": {"required": "*nda*.pdf"}}
    c.post("/connectors/gmail/sync", json=body, headers=h)
    c.post("/connectors/gmail/sync", json=body, headers=h)  # same gap: no second alert
    alerts = [a for a in c.get("/alerts", headers=h).json() if a["kind"] == "dd" and "data-room" in a["title"]]
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "warning" and "atlas: 1 required" in alerts[0]["title"]
    assert "- *nda*.pdf" in alerts[0]["detail"]


def test_satisfied_checklist_raises_nothing(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(gmail_routes()))
    h = new_tenant(c, "room-ok")
    c.post("/connectors/gmail/sync", json={"token": "tok", "deal": "atlas", "options": {"required": "*"}},
           headers=h)
    assert not [a for a in c.get("/alerts", headers=h).json() if "data-room" in a["title"]]
