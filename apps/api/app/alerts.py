"""Proactive layer: watchers scan stored data and write alerts to an inbox.

A watcher is a function (db, tenant_id) -> list[AlertDraft]. Each draft carries a dedupe key, so
scanning twice never repeats an alert, and the ids of the facts behind it, so every alert opens to
its sources. Watchers read the whole tenant, so only unrestricted keys may scan or read the inbox.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Alert
from app.portfolio import Covenant, PortfolioCompany, evaluate_covenant

SEVERITIES = ("info", "warning", "critical")
STATUSES = ("new", "read", "dismissed")


@dataclass
class AlertDraft:
    kind: str
    severity: str
    title: str
    detail: str
    dedupe_key: str
    fact_ids: list[int] = field(default_factory=list)


Watcher = Callable[[Session, str], list[AlertDraft]]
WATCHERS: dict[str, Watcher] = {}


def register_watcher(name: str):
    def deco(fn: Watcher) -> Watcher:
        WATCHERS[name] = fn
        return fn
    return deco


@register_watcher("covenants")
def covenant_watch(db: Session, tenant_id: str) -> list[AlertDraft]:
    out = []
    for cov in db.query(Covenant).filter_by(tenant_id=tenant_id):
        company = db.get(PortfolioCompany, cov.company_id)
        name = company.name if company else f"company {cov.company_id}"
        for t in evaluate_covenant(db, cov):
            if t["status"] not in ("breach", "unit_mismatch"):
                continue
            ids = [t["observation_fact_id"], t["threshold_fact_id"]]
            if t["status"] == "breach":
                title = f"{name}: {cov.kpi_metric} breaches covenant ({cov.operator} {t['threshold']} {t['unit']})"
                detail = f"{t['period']}: {t['value']} {t['unit']} against threshold {t['threshold']}."
                sev = "critical"
            else:
                title = f"{name}: {cov.kpi_metric} cannot be tested (units differ)"
                detail = f"{t['period']}: observation and threshold use different units."
                sev = "warning"
            out.append(AlertDraft("covenant", sev, title, detail,
                                  f"covenant:{cov.id}:{t['period']}:{t['status']}:{t['value']}", ids))
    return out


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def scan(db: Session, tenant_id: str, only: list[str] | None = None) -> list[Alert]:
    """Run watchers; returns the alerts created by this scan."""
    created: list[Alert] = []
    for name, w in WATCHERS.items():
        if only and name not in only:
            continue
        for d in w(db, tenant_id):
            if d.severity not in SEVERITIES:
                continue
            if db.query(Alert).filter_by(tenant_id=tenant_id, dedupe_key=d.dedupe_key).first():
                continue
            a = Alert(tenant_id=tenant_id, kind=d.kind, severity=d.severity, title=d.title, detail=d.detail,
                      dedupe_key=d.dedupe_key, fact_ids=json.dumps(d.fact_ids), status="new", created_at=_now())
            db.add(a)
            created.append(a)
    db.commit()
    return created


def alert_dict(a: Alert) -> dict:
    return {"id": a.id, "kind": a.kind, "severity": a.severity, "title": a.title, "detail": a.detail,
            "fact_ids": json.loads(a.fact_ids), "status": a.status, "created_at": a.created_at}


def set_status(db: Session, tenant_id: str, alert_id: int, status: str) -> Alert | None:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    a = db.query(Alert).filter_by(id=alert_id, tenant_id=tenant_id).one_or_none()
    if a is not None:
        a.status = status
        db.commit()
    return a
