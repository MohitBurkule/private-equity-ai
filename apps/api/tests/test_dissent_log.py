"""Firm-wide dissent log: every recorded dissent, newest first. SYNTHETIC: deal names and views made up."""

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_lists_only_recorded_dissents_newest_first():
    h = new_tenant(c, "dissent-log")
    for deal in ("Synth Dissent A", "Synth Dissent B"):
        c.post("/deals", json={"name": deal}, headers=h)
    c.post("/ic/decisions", json={"deal": "Synth Dissent A", "outcome": "proceed", "rationale": "Good fit."}, headers=h)
    c.post("/ic/decisions", json={"deal": "Synth Dissent A", "outcome": "pass", "rationale": "Too rich.",
                                  "dissent": "Price fair to me.", "dissenter": "Partner A"}, headers=h)
    c.post("/ic/decisions", json={"deal": "Synth Dissent B", "outcome": "hold", "rationale": "Wait.",
                                  "dissent": "Should proceed now.", "dissenter": "Partner B"}, headers=h)
    log = c.get("/ic/dissent-log", headers=h).json()
    assert [r["deal"] for r in log] == ["Synth Dissent B", "Synth Dissent A"]
    assert all(r["dissent"] for r in log)
    assert c.get("/ic/dissent-log", params={"limit": 1}, headers=h).json()[0]["dissenter"] == "Partner B"
