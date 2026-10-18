"""KPI packs mailed to a company's inbox alias. SYNTHETIC: company names, aliases and figures are made up."""

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant
from tests.test_kpi_workbook import _pack

c = TestClient(app)
ROWS = [("Revenue", "2026-09", 55, "GBP m"), ("Headcount", "2026-09", 12, "FTE")]


def _mail(h, alias, data, name="pack.xlsx"):
    return c.post("/portfolio/kpi-packs/inbox", data={"alias": alias},
                  files={"file": (name, data, "application/vnd.ms-excel")}, headers=h)


def test_alias_routes_pack_to_its_company_with_cited_observations():
    h = new_tenant(c, "inbox-alias")
    cid = c.post("/portfolio/companies", json={"name": "Synth Inbox Co"}, headers=h).json()["id"]
    assert c.put(f"/portfolio/companies/{cid}/inbox-alias", json={"alias": "Synth-KPI"}, headers=h).json() == {"alias": "synth-kpi"}
    r = _mail(h, "SYNTH-kpi", _pack(ROWS))
    assert r.status_code == 200, r.text
    assert r.json()["company_id"] == cid and len(r.json()["observations"]) == 2
    assert len(c.get(f"/portfolio/companies/{cid}/kpis", headers=h).json()) == 2


def test_unknown_alias_is_404_and_alias_clash_is_422():
    h = new_tenant(c, "inbox-alias-bad")
    assert _mail(h, "nobody-here", _pack(ROWS)).status_code == 404
    a = c.post("/portfolio/companies", json={"name": "Synth A"}, headers=h).json()["id"]
    b = c.post("/portfolio/companies", json={"name": "Synth B"}, headers=h).json()["id"]
    assert c.put(f"/portfolio/companies/{a}/inbox-alias", json={"alias": "shared-one"}, headers=h).status_code == 200
    assert c.put(f"/portfolio/companies/{b}/inbox-alias", json={"alias": "shared-one"}, headers=h).status_code == 422
    assert c.put(f"/portfolio/companies/{b}/inbox-alias", json={"alias": "bad alias!"}, headers=h).status_code == 422
