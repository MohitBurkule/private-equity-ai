"""Per-connection re-sync alerts: stale after the connection's own limit, or failed on the last run."""
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.connectors.resync import DEFAULT_STALE_HOURS, problem, stale_after
from app.main import SessionLocal, app
from app.models import Alert, Connection
from app.rls import bind_tenant
from tests.helpers import new_tenant_id

c = TestClient(app)
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def conn(last_run=None, status="ok: 3 new, 0 unchanged", options="{}"):
    return Connection(tenant_id="t", connector="s3", options=options, token_sealed="x", created_by="k",
                      last_run=last_run.isoformat() if last_run else None, last_status=status)


def test_never_run_raises_nothing():
    assert problem(conn(), NOW) is None


def test_fresh_ok_run_raises_nothing():
    assert problem(conn(NOW - timedelta(hours=2)), NOW) is None


def test_run_older_than_default_limit_is_stale():
    kind, reason = problem(conn(NOW - timedelta(hours=DEFAULT_STALE_HOURS + 1)), NOW)
    assert kind == "connector_stale" and "limit 24 h" in reason


def test_per_connection_limit_overrides_default():
    row = conn(NOW - timedelta(hours=6), options='{"stale_after_hours": 4}')
    assert problem(row, NOW)[0] == "connector_stale"
    assert problem(conn(NOW - timedelta(hours=6), options='{"stale_after_hours": 8}'), NOW) is None


def test_failed_last_run_is_an_error_whatever_its_age():
    kind, reason = problem(conn(NOW - timedelta(minutes=5), status="error: 401 unauthorized"), NOW)
    assert kind == "connector_error" and "401" in reason


def test_bad_limit_falls_back_to_default():
    assert stale_after('{"stale_after_hours": "soon"}') == DEFAULT_STALE_HOURS
    assert stale_after('{"stale_after_hours": -3}') == DEFAULT_STALE_HOURS
    assert stale_after("not json") == DEFAULT_STALE_HOURS


def test_check_endpoint_raises_once_per_stale_run():
    h, tid = new_tenant_id(c, "resync")
    with SessionLocal() as s:
        bind_tenant(s, tid)
        s.add(Connection(tenant_id=tid, connector="s3", options="{}", token_sealed="x", created_by="k",
                         last_run=(datetime.now(UTC) - timedelta(days=3)).isoformat(), last_status="ok: done"))
        s.commit()
    first = c.post("/connectors/resync-check", headers=h).json()["raised"]
    again = c.post("/connectors/resync-check", headers=h).json()["raised"]
    assert [a["kind"] for a in first] == ["connector_stale"] and again == []
    with SessionLocal() as s:
        bind_tenant(s, tid)
        assert s.query(Alert).filter_by(tenant_id=tid, kind="connector_stale").count() == 1


def test_run_due_tick_also_raises_resync_alerts():
    h, tid = new_tenant_id(c, "resync-tick")
    with SessionLocal() as s:
        bind_tenant(s, tid)
        s.add(Connection(tenant_id=tid, connector="s3", options="{}", token_sealed="x", created_by="k",
                         last_run=(datetime.now(UTC) - timedelta(days=2)).isoformat(), last_status="ok: done"))
        s.commit()
    body = c.post("/connections/run-due", headers=h).json()
    assert body["resync_alerts"] == 1
    assert c.post("/connections/run-due", headers=h).json()["resync_alerts"] == 0
