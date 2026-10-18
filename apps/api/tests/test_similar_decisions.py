"""Past IC decisions on similar deals. SYNTHETIC: deal names, SIC codes and sponsors are made up."""

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def _deal(h, name, sic=None, sponsor=None):
    return c.post("/deals", json={"name": name, "sic": sic, "sponsor": sponsor}, headers=h)


def _decide(h, deal, outcome, rationale, dissent=None, dissenter=None):
    return c.post("/ic/decisions", json={"deal": deal, "outcome": outcome, "rationale": rationale,
                                         "dissent": dissent, "dissenter": dissenter}, headers=h)


def test_matches_by_sic_division_and_sponsor_with_dissent_first():
    h = new_tenant(c, "similar-decisions")
    _deal(h, "Synth New Co", sic="7372", sponsor="Synth Capital, LLC")
    _deal(h, "Synth Old Co", sic="7374")          # same SIC division (73)
    _deal(h, "Synth Sponsor Co", sic="2834", sponsor="SYNTH CAPITAL")  # same sponsor after normalising
    _deal(h, "Synth Unrelated Co", sic="5411")
    assert _decide(h, "Synth Unrelated Co", "pass", "Too small.").status_code == 201
    _decide(h, "Synth Old Co", "proceed", "Recurring revenue.")
    _decide(h, "Synth Sponsor Co", "pass", "Price too high.", dissent="Thought the multiple fair.",
            dissenter="Partner A")
    out = c.get("/deals/Synth New Co/similar-decisions", headers=h).json()
    assert [r["deal"] for r in out["matches"]] == ["Synth Sponsor Co", "Synth Old Co"]
    assert out["matches"][0]["matched_on"] == ["same sponsor"]
    assert out["matches"][1]["matched_on"] == ["same SIC division"]
    assert out["matches"][0]["dissenter"] == "Partner A" and out["matches"][0]["decision_id"]


def test_unknown_deal_is_404():
    h = new_tenant(c, "similar-decisions-404")
    assert c.get("/deals/Nobody/similar-decisions", headers=h).status_code == 404
