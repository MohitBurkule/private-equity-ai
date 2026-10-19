"""Stage ageing: a deal over its stage limit is flagged, and a stage move restarts its clock."""
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

import app.main as m
from app import alerts
from app.main import app
from app.models import Deal
from app.rls import bind_tenant
from tests.helpers import new_tenant_id

c = TestClient(app)


def _set_stage_since(tid, name, days):
    db = m.SessionLocal()
    bind_tenant(db, tid)
    db.query(Deal).filter_by(tenant_id=tid, name=name).update(
        {"stage_since": (datetime.now(UTC) - timedelta(days=days)).isoformat()})
    db.commit()
    db.close()


def _drafts(tid):
    db = m.SessionLocal()
    bind_tenant(db, tid)
    out = alerts.stage_ageing(db, tid)
    db.close()
    return out


def test_flags_only_over_limit_and_stage_move_restarts_clock():
    h, tid = new_tenant_id(c, "stage1")
    c.post("/deals", headers=h, json={"name": "Old Co", "stage": "cim"})
    c.post("/deals", headers=h, json={"name": "New Co", "stage": "cim"})
    _set_stage_since(tid, "Old Co", 40)
    _set_stage_since(tid, "New Co", 5)
    assert [d.title for d in _drafts(tid)] == ["Old Co: 40 days in cim (limit 30)"]
    assert c.patch("/deals/Old Co", headers=h, json={"stage": "ioi"}).status_code == 200
    assert _drafts(tid) == []
