from app import notify
from app.main import SessionLocal
from app.models import Alert
from app.rls import bind_tenant
from tests.test_mnpi_docs import ADMIN, c
from tests.test_oidc import _sso, _token


def _add(tenant, kind, title):
    db = SessionLocal()
    bind_tenant(db, tenant)
    db.add(Alert(tenant_id=tenant, kind=kind, severity="warning", title=title, detail="d",
                 dedupe_key=f"{title}-{kind}", fact_ids="[]", status="new", created_at="2026-10-17"))
    db.commit()
    db.close()


def test_mnpi_deal_alerts_stay_out_of_a_digest_for_people_not_cleared(monkeypatch):
    _sso(monkeypatch)
    t = c.post("/admin/tenants", json={"name": "digest-mnpi"}, headers=ADMIN).json()
    tid = t["tenant_id"]
    creator = {"Authorization": f"Bearer {t['api_key']}"}
    assert c.post("/deals", headers=creator, json={"name": "Secret", "mnpi": True}).status_code == 201
    _add(tid, "deal", "Secret: no update for 40 days (stage ic)")
    _add(tid, "deal", "Open Co: no update for 40 days (stage ic)")
    outsider = {"Authorization": f"Bearer {_token(tenant=tid, role='partner', sub='olive')}"}
    assert c.put("/me/digest", headers=outsider, json={"email": "olive@firm.test"}).status_code == 200
    sent = []
    monkeypatch.setattr(notify, "send_email", lambda to, subj, body: sent.append(body))
    assert c.post("/me/digest/send", headers=outsider).json() == {"sent": 1}
    assert "Open Co" in sent[0] and "Secret" not in sent[0]
