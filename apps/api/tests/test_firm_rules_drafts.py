import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import SessionLocal, app
from app.models import FirmKnowledge
from app.rls import bind_tenant

c = TestClient(app)


def test_accepted_rules_quoted_in_memo_and_report_pending_ignored():
    t = c.post("/admin/tenants", json={"name": "fr1"}, headers={"X-Admin-Token": "test-admin"}).json()
    h, tid = {"Authorization": f"Bearer {t['api_key']}"}, t["tenant_id"]
    wb = Workbook()
    wb.active["A1"] = "Board meets quarterly"
    b = io.BytesIO()
    wb.save(b)
    doc = c.post("/documents", files={"file": ("p.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]
    with SessionLocal() as s:
        bind_tenant(s, tid)
        s.add(FirmKnowledge(tenant_id=tid, key="board_meeting_frequency", value="quarterly", document_id=doc,
                            page=1, quote="Board meets quarterly", status="accepted"))
        s.add(FirmKnowledge(tenant_id=tid, key="lp_reporting_tone", value="plain", document_id=doc,
                            page=1, quote="Board meets quarterly", status="pending"))
        s.commit()
    md = c.get("/memo", params={"entity": "Nobody"}, headers=h).json()["markdown"]
    assert "Firm rules applied" in md
    assert "Board meeting frequency: quarterly" in md and '"Board meets quarterly"' in md
    assert "plain" not in md  # pending tone never applies
    rep = c.get("/portfolio/report", headers=h).json()
    assert [r["key"] for r in rep["rules"]] == ["board_meeting_frequency"]
    assert c.get("/portfolio/report.docx", headers=h).status_code == 200


def test_no_accepted_rules_no_section():
    t = c.post("/admin/tenants", json={"name": "fr2"}, headers={"X-Admin-Token": "test-admin"}).json()
    h = {"Authorization": f"Bearer {t['api_key']}"}
    md = c.get("/memo", params={"entity": "Nobody"}, headers=h).json()["markdown"]
    assert "Firm rules" not in md
    assert c.get("/portfolio/report", headers=h).json()["rules"] == []
