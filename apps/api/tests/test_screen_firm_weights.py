from fastapi.testclient import TestClient

from app import edgar, secfeed
from app.alerts import screening_weights
from app.main import SessionLocal, app
from app.models import Document, FirmKnowledge, Target
from app.rls import bind_tenant

c = TestClient(app)


def new_tenant(name):
    t = c.post("/admin/tenants", json={"name": name}, headers={"X-Admin-Token": "test-admin"}).json()
    return {"Authorization": f"Bearer {t['api_key']}"}, t["tenant_id"]


def _seed(h):
    c.post("/targets", headers=h, json=[
        {"name": "Delta Co", "source": "manual", "source_ref": "d", "sector": "Software", "country": "UK"},
    ])


def _firm_rule(h, tid, key, value):
    with SessionLocal() as s:
        bind_tenant(s, tid)
        doc = Document(id=f"rule-{key}-{tid}", tenant_id=tid, sha256="0" * 64, filename="rules.pdf", n_pages=1)
        s.add(doc)
        s.add(FirmKnowledge(tenant_id=tid, key=key, value=value, document_id=doc.id, page=1,
                            quote=value, status="accepted"))
        s.commit()


def test_weight_rule_parses_named_criteria_only():
    assert screening_weights("Sector: 2, country: 1; revenue weight = 0") == {"sector": 2.0, "country": 1.0,
                                                                              "revenue": 0.0}
    assert screening_weights("Revenue matters a lot") == {}


def test_firm_weight_rule_applies_when_request_has_no_weights():
    h, tid = new_tenant("firm-weights")
    _seed(h)
    _firm_rule(h, tid, "screening_weights", "revenue: 0")
    body = c.post("/targets/screen", headers=h, json={"sectors": ["Software"], "countries": ["UK"],
                                                      "min_revenue": "100"}).json()
    assert body["items"][0]["score"] == 1.0
    assert body["applied"]["weights"] == {"revenue": 0.0}
    assert body["applied"]["weights_source"]["key"] == "screening_weights"


def test_request_weights_override_the_firm_rule():
    h, tid = new_tenant("firm-weights-override")
    _seed(h)
    _firm_rule(h, tid, "screening_weights", "revenue: 0")
    body = c.post("/targets/screen", headers=h, json={"sectors": ["Software"], "countries": ["UK"],
                                                      "min_revenue": "100", "weights": {}}).json()
    assert body["applied"]["weights_source"] is not None
    body = c.post("/targets/screen", headers=h, json={"sectors": ["Software"], "countries": ["UK"],
                                                      "min_revenue": "100", "weights": {"revenue": 1}}).json()
    assert body["applied"]["weights_source"] is None
    assert body["items"][0]["score"] == 0.67


def test_refresh_updates_sec_target_and_counts_failures(monkeypatch):
    h, tid = new_tenant("refresh")
    c.post("/targets/import/sec", headers=h, json={
        "submissions": {"cik": 320193, "name": "Old Name", "sic": "7372", "sicDescription": "Services",
                        "addresses": {"business": {"isForeignLocation": False, "stateOrCountry": "CA"}}},
        "companyfacts": None})
    c.post("/targets", headers=h, json=[{"name": "Gone Ltd", "source": "companies_house", "source_ref": "99999999"}])

    def fake_sec(cik):
        return ({"cik": int(cik), "name": "New Name", "sic": "7372", "sicDescription": "Services",
                 "addresses": {"business": {"isForeignLocation": False, "stateOrCountry": "CA"}}}, None)

    monkeypatch.setattr(secfeed, "default_fetch", lambda url: b'{"cik": 320193, "name": "New Name"}')
    monkeypatch.setattr(edgar, "fetch_companyfacts", lambda cik, get=None: None)
    monkeypatch.setattr("app.main.fetch_companyfacts", lambda cik, get=None: None)
    monkeypatch.setattr("app.main.ch_mod.fetch_company", lambda number, api_key=None: None)
    out = c.post("/targets/refresh", headers=h).json()
    assert out == {"checked": 2, "refreshed": 1, "failed": 1, "dissolved": 0}
    with SessionLocal() as s:
        bind_tenant(s, tid)
        names = {t.source_ref: t.name for t in s.query(Target).filter_by(tenant_id=tid)}
    assert names["0000320193"] == "New Name" and names["99999999"] == "Gone Ltd"
