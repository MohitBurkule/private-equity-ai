from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}


def tenant(name):
    t = c.post("/admin/tenants", json={"name": name}, headers=ADMIN).json()
    return t["tenant_id"], {"Authorization": f"Bearer {t['api_key']}"}


def test_sic_query_finds_deals_filed_under_it_and_respects_walls():
    tid, owner = tenant("seen-sic")
    assert c.post("/deals", headers=owner, json={"name": "Acme", "stage": "ic", "sic": "62012"}).status_code == 201
    assert c.post("/deals", headers=owner, json={"name": "Mine", "stage": "ic", "sic": "41201"}).status_code == 201
    assert c.post("/deals", headers=owner, json={"name": "Secret", "stage": "ic", "sic": "62012",
                                                 "mnpi": True}).status_code == 201
    r = c.post(f"/admin/tenants/{tid}/keys", json={"role": "analyst", "deals": ["Acme"]}, headers=ADMIN).json()
    scoped = {"Authorization": f"Bearer {r['api_key']}"}

    everyone = c.get("/seen-before", params={"q": "62012"}, headers=owner).json()
    assert sorted(h["name"] for h in everyone["hits"]) == ["Acme", "Secret"]
    assert {h["rule"] for h in everyone["hits"]} == {"sic"}

    narrow = c.get("/seen-before", params={"q": "62012"}, headers=scoped).json()
    assert [h["name"] for h in narrow["hits"]] == ["Acme"]  # Secret is walled off from this key


def test_names_still_match_and_short_numbers_do_not_count_as_sic():
    _, h = tenant("seen-name")
    assert c.post("/deals", headers=h, json={"name": "Acme Holdings", "stage": "ic", "sic": "62012"}).status_code == 201
    by_name = c.get("/seen-before", params={"q": "Acme Holdings, Inc."}, headers=h).json()
    assert [x["rule"] for x in by_name["hits"]] == ["exact"]
    assert c.get("/seen-before", params={"q": "2012"}, headers=h).json()["hits"] == []
