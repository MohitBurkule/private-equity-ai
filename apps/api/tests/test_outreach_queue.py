from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}


def _tenant():
    t = c.post("/admin/tenants", json={"name": "queue"}, headers=ADMIN).json()
    return t["tenant_id"], {"Authorization": f"Bearer {t['api_key']}"}


def _key(tid, role):
    r = c.post(f"/admin/tenants/{tid}/keys", json={"role": role}, headers=ADMIN)
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['api_key']}"}


def _queue_one(h, name):
    c.post("/targets", headers=h, json=[{"name": name, "source": "manual", "source_ref": name, "sector": "Software"}])
    tid = next(t["id"] for t in c.get("/targets", headers=h).json()["items"] if t["name"] == name)
    return c.post("/targets/outreach/queue", headers=h, json={"target_ids": [tid], "sender": "Ana", "firm": "Firm"}).json()["items"][0]


def test_queue_then_approve_then_send_once(monkeypatch):
    _, h = _tenant()
    item = _queue_one(h, "Delta Ltd")
    assert item["status"] == "pending"
    sent = []
    monkeypatch.setattr("app.notify.send_email", lambda *a, **k: sent.append(a))
    assert c.post(f"/targets/outreach/queue/{item['id']}/send", headers=h, json={"to": ["ic@example.com"]}).status_code == 409
    assert sent == []
    assert c.post(f"/targets/outreach/queue/{item['id']}/review", headers=h, json={"decision": "approve"}).json()["status"] == "approved"
    assert c.post(f"/targets/outreach/queue/{item['id']}/send", headers=h, json={"to": ["ic@example.com"]}).status_code == 200
    assert len(sent) == 1
    assert c.post(f"/targets/outreach/queue/{item['id']}/send", headers=h, json={"to": ["ic@example.com"]}).status_code == 409


def test_analyst_key_cannot_review_or_send():
    tid, h = _tenant()
    item = _queue_one(h, "Eta Ltd")
    analyst = _key(tid, "analyst")
    assert c.post(f"/targets/outreach/queue/{item['id']}/review", headers=analyst, json={"decision": "approve"}).status_code == 403


def test_queue_list_and_bad_decision():
    _, h = _tenant()
    item = _queue_one(h, "Zeta Ltd")
    rows = c.get("/targets/outreach/queue?status=pending", headers=h).json()["items"]
    assert [r["id"] for r in rows] == [item["id"]]
    assert c.post(f"/targets/outreach/queue/{item['id']}/review", headers=h, json={"decision": "maybe"}).status_code == 422


def test_queue_is_not_reachable_from_agents_or_workflows():
    from app.main import ag, wf_mod
    assert not any("outreach" in name for name in ag.TOOLS)
    assert not any("outreach" in k for k in wf_mod.KINDS)
