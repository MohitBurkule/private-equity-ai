"""Human-written post-mortems per deal, surfaced next to similar past decisions. SYNTHETIC: names made up."""

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def _deal(h, name, sic=None, sponsor=None):
    return c.post("/deals", json={"name": name, "sic": sic, "sponsor": sponsor}, headers=h)


def test_postmortem_is_recorded_listed_and_surfaced_for_similar_deals():
    h = new_tenant(c, "postmortem")
    _deal(h, "Synth Exited Co", sic="7372", sponsor="Synth Capital")
    _deal(h, "Synth Next Co", sic="7374")
    r = c.post("/deals/Synth Exited Co/postmortems", headers=h, json={
        "outcome": "exited", "lesson": "Exit multiple held because churn stayed under 5%.",
        "source_url": "https://example.com/synth-memo.pdf"})
    assert r.status_code == 201, r.text
    listed = c.get("/deals/Synth Exited Co/postmortems", headers=h).json()
    assert len(listed) == 1 and listed[0]["recorded_by"]
    out = c.get("/deals/Synth Next Co/similar-decisions", headers=h).json()
    assert out["postmortems"][0]["lesson"].startswith("Exit multiple") and out["postmortems"][0]["matched_on"] == ["same SIC division"]


def test_bad_outcome_and_non_https_source_are_422():
    h = new_tenant(c, "postmortem-bad")
    _deal(h, "Synth Bad Co")
    assert c.post("/deals/Synth Bad Co/postmortems", headers=h,
                  json={"outcome": "sold", "lesson": "x"}).status_code == 422
    assert c.post("/deals/Synth Bad Co/postmortems", headers=h,
                  json={"outcome": "lost", "lesson": "x", "source_url": "http://insecure.example"}).status_code == 422
