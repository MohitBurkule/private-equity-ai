from app import notify
from app.main import SessionLocal
from app.models import Alert
from tests.test_oidc import _sso, _tenant, _token, c


def _alert(tenant, title, severity):
    db = SessionLocal()
    db.add(Alert(tenant_id=tenant, kind="covenant", severity=severity, title=title, detail="d",
                 dedupe_key=f"{title}-{severity}", fact_ids="[]", status="new", created_at="2026-10-17"))
    db.commit()
    db.close()


def test_digest_is_per_person_with_their_own_severity_floor_and_watermark(monkeypatch):
    _sso(monkeypatch)
    t = _tenant("digest-pref")
    tid = t["tenant_id"]
    ann = {"Authorization": f"Bearer {_token(tenant=tid, role='analyst', sub='ann')}"}
    ben = {"Authorization": f"Bearer {_token(tenant=tid, role='analyst', sub='ben')}"}
    assert c.put("/me/digest", headers=ann, json={"email": "ann@firm.test", "min_severity": "critical"}).status_code == 200
    assert c.put("/me/digest", headers=ben, json={"email": "ben@firm.test"}).status_code == 200
    _alert(tid, "Crit one", "critical")
    _alert(tid, "Info one", "info")
    sent = []
    monkeypatch.setattr(notify, "send_email", lambda to, subj, body: sent.append((to, subj, body)))
    assert c.post("/me/digest/send", headers=ann).json() == {"sent": 1}
    assert sent[0][0] == ["ann@firm.test"] and "Crit one" in sent[0][2] and "Info one" not in sent[0][2]
    assert c.post("/me/digest/send", headers=ann).json() == {"sent": 0}  # watermark: nothing twice
    assert c.post("/me/digest/send", headers=ben).json() == {"sent": 2}  # ben gets everything, own watermark
    assert sent[-1][0] == ["ben@firm.test"]


def test_api_key_cannot_hold_a_digest_and_sign_in_is_required():
    h = {"Authorization": f"Bearer {_tenant('digest-key')['api_key']}"}
    assert c.put("/me/digest", headers=h, json={"email": "x@firm.test"}).status_code == 403
    assert c.post("/me/digest/send", headers=h).status_code == 403


def test_send_before_setting_a_digest_is_404(monkeypatch):
    _sso(monkeypatch)
    tid = _tenant("digest-none")["tenant_id"]
    h = {"Authorization": f"Bearer {_token(tenant=tid, role='analyst', sub='cy')}"}
    assert c.post("/me/digest/send", headers=h).status_code == 404
