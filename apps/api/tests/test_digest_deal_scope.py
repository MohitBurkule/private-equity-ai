from app import notify
from app.main import SessionLocal
from app.models import Alert
from tests.test_oidc import _sso, _tenant, _token, c


def _add(tenant, kind, title):
    db = SessionLocal()
    db.add(Alert(tenant_id=tenant, kind=kind, severity="warning", title=title, detail="d",
                 dedupe_key=f"{title}-{kind}", fact_ids="[]", status="new", created_at="2026-10-17"))
    db.commit()
    db.close()


def test_deal_scoped_sign_in_gets_only_its_deals_alerts(monkeypatch):
    _sso(monkeypatch)
    tid = _tenant("digest-deal-scope")["tenant_id"]
    scoped = {"Authorization": f"Bearer {_token(tenant=tid, role='analyst', sub='dana', deals=['Acme'])}"}
    _add(tid, "deal", "Acme: no update for 40 days (stage dd)")
    _add(tid, "deal", "Other Co: no update for 40 days (stage ic)")
    _add(tid, "dd", "Acme: 3 DD request(s) open for 14+ days")
    _add(tid, "covenant", "Acme covenant breach")  # no deal in the title: not in a deal-scoped digest
    assert c.put("/me/digest", headers=scoped, json={"email": "dana@firm.test"}).status_code == 200
    sent = []
    monkeypatch.setattr(notify, "send_email", lambda to, subj, body: sent.append(body))
    assert c.post("/me/digest/send", headers=scoped).json() == {"sent": 2}
    assert "Acme: no update" in sent[0] and "DD request" in sent[0]
    assert "Other Co" not in sent[0] and "covenant" not in sent[0]
    assert c.post("/me/digest/send", headers=scoped).json() == {"sent": 0}


def test_whole_tenant_sign_in_still_gets_everything(monkeypatch):
    _sso(monkeypatch)
    tid = _tenant("digest-whole")["tenant_id"]
    whole = {"Authorization": f"Bearer {_token(tenant=tid, role='partner', sub='pat')}"}
    _add(tid, "deal", "Other Co: no update for 40 days (stage ic)")
    _add(tid, "covenant", "Acme covenant breach")
    assert c.put("/me/digest", headers=whole, json={"email": "pat@firm.test"}).status_code == 200
    sent = []
    monkeypatch.setattr(notify, "send_email", lambda to, subj, body: sent.append(body))
    assert c.post("/me/digest/send", headers=whole).json() == {"sent": 2}
