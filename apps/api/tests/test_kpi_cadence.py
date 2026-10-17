from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app import alerts
from app.alerts import cadence_days, kpi_overdue


def test_cadence_parsing():
    assert cadence_days("KPI packs are due monthly") == 31
    assert cadence_days("Quarterly reporting, 10 days after quarter end") == 92
    assert cadence_days("send within 45 days") == 45
    assert cadence_days("when convenient") is None


def stamp(days):
    return (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")


class FakeDb:
    def __init__(self, companies):
        self.companies = companies

    def query(self, model):
        return SimpleNamespace(filter_by=lambda **kw: self.companies)


def test_overdue_flagged_fresh_and_empty_skipped(monkeypatch):
    rule = SimpleNamespace(value="KPI packs are due monthly", document_id=7, page=2, quote="KPI packs are due monthly")
    monkeypatch.setattr(alerts.fk, "newest_accepted", lambda db, t, key: rule)
    co = {
        "Stale": [SimpleNamespace(observed_at=stamp(60))],
        "Fresh": [SimpleNamespace(observed_at=stamp(5))],
        "Empty": [],
    }
    companies = [SimpleNamespace(id=i, name=n) for i, n in enumerate(co, 1)]
    monkeypatch.setattr(alerts, "current_kpis", lambda db, t, cid: co[companies[cid - 1].name])
    out = kpi_overdue(FakeDb(companies), "t")
    assert len(out) == 1
    assert out[0].title == "Stale: no KPI update for 60 days (firm cadence 31 days)"
    assert "KPI packs are due monthly" in out[0].detail


def test_no_rule_no_alert(monkeypatch):
    monkeypatch.setattr(alerts.fk, "newest_accepted", lambda db, t, key: None)
    assert kpi_overdue(FakeDb([]), "t") == []
