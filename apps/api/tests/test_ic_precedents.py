from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}


def tenant(name):
    t = c.post("/admin/tenants", json={"name": name}, headers=ADMIN).json()
    return t["tenant_id"], {"Authorization": f"Bearer {t['api_key']}"}


def scoped_key(tid, deals):
    r = c.post(f"/admin/tenants/{tid}/keys", json={"role": "analyst", "deals": deals}, headers=ADMIN)
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['api_key']}"}


def decide(h, deal, outcome):
    r = c.post("/ic/decisions", headers=h, json={"deal": deal, "outcome": outcome, "rationale": f"{deal} {outcome}"})
    assert r.status_code == 201, r.text


def seed(h):
    for name, stage, mnpi in [("Acme", "ic", False), ("Beta", "ic", False), ("Gamma", "dd", False),
                              ("Secret", "ic", True)]:
        assert c.post("/deals", headers=h, json={"name": name, "stage": stage, "mnpi": mnpi}).status_code == 201
    decide(h, "Beta", "hold")
    decide(h, "Beta", "proceed")  # the later view is the one that counts
    decide(h, "Gamma", "proceed")  # different stage: never a precedent for Acme
    decide(h, "Secret", "pass")  # walled deal: visible here because this key flagged it


def test_precedents_compare_same_stage_deals_the_key_can_see():
    _, h = tenant("precedents")
    seed(h)
    r = c.get("/ic/precedents", params={"deal": "Acme"}, headers=h).json()
    assert r["stage"] == "ic"
    assert [p["deal"] for p in r["precedents"]] == ["Beta", "Secret"]
    assert r["precedents"][0]["outcome"] == "proceed"
    assert r["outcome_counts"] == {"proceed": 1, "pass": 1}
    assert r["compared_deals"] == 2  # Gamma is at another stage and never counted


def test_scoped_key_compares_only_deals_in_its_scope():
    tid, owner = tenant("precedents-scoped")
    seed(owner)
    h = scoped_key(tid, ["Acme", "Secret"])  # Secret is walled but named, so this key may see it
    r = c.get("/ic/precedents", params={"deal": "Acme"}, headers=h).json()
    assert [p["deal"] for p in r["precedents"]] == ["Secret"]
    assert r["compared_deals"] == 1  # Beta is outside this key's scope and is not counted at all


def test_target_outside_scope_is_refused():
    tid, owner = tenant("precedents-refuse")
    seed(owner)
    h = scoped_key(tid, ["Acme"])
    assert c.get("/ic/precedents", params={"deal": "Beta"}, headers=h).status_code == 403
    assert c.get("/ic/precedents", params={"deal": "Nope"}, headers=owner).status_code == 404


def test_sic_narrows_precedents_to_the_same_industry():
    _, h = tenant("precedents-sic")
    for name, sic in [("Acme", "62012"), ("Beta", "62012"), ("Gamma", "41201")]:
        assert c.post("/deals", headers=h, json={"name": name, "stage": "ic", "sic": sic}).status_code == 201
    decide(h, "Beta", "proceed")
    decide(h, "Gamma", "pass")
    r = c.get("/ic/precedents", params={"deal": "Acme"}, headers=h).json()
    assert r["match"] == "sic+stage" and r["sic"] == "62012"
    assert [p["deal"] for p in r["precedents"]] == ["Beta"]
    assert r["compared_deals"] == 1


def test_no_sic_falls_back_to_stage_only():
    _, h = tenant("precedents-nosic")
    assert c.post("/deals", headers=h, json={"name": "Acme", "stage": "ic"}).status_code == 201
    assert c.post("/deals", headers=h, json={"name": "Beta", "stage": "ic", "sic": "41201"}).status_code == 201
    decide(h, "Beta", "hold")
    r = c.get("/ic/precedents", params={"deal": "Acme"}, headers=h).json()
    assert r["match"] == "stage" and r["sic"] is None
    assert [p["deal"] for p in r["precedents"]] == ["Beta"]
