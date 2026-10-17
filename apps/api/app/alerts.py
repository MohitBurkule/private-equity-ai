"""Proactive layer: watchers scan stored data and write alerts to an inbox.

A watcher is a function (db, tenant_id) -> list[AlertDraft]. Each draft carries a dedupe key, so
scanning twice never repeats an alert, and the ids of the facts behind it, so every alert opens to
its sources. Watchers read the whole tenant, so only unrestricted keys may scan or read the inbox.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app import firm_knowledge as fk
from app import secfeed
from app.models import Alert, DDRequest, Deal, Target
from app.portfolio import (
    Covenant,
    PortfolioCompany,
    current_kpis,
    evaluate_covenant,
)
from app.targets import Criteria, evaluate

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


STALL_DAYS = 30  # default when the firm has no accepted deal_stall_days rule
DD_OPEN_DAYS = 14  # default when the firm has no accepted dd_response_days rule


def _age_days(stamp: str | None) -> int | None:
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(stamp)).days if stamp else None
    except ValueError:
        return None


def _firm_days(db: Session, tenant_id: str, key: str, default: int) -> int:
    """The firm's accepted number for `key` (cited, human-accepted), else the default."""
    found = fk.limit(db, tenant_id, key)
    if found is None or found[0] <= 0:
        return default
    return int(found[0])


_CADENCE_WORDS = {"daily": 1, "weekly": 7, "monthly": 31, "quarterly": 92, "semi-annual": 183, "annual": 366}


def cadence_days(text: str) -> int | None:
    """Days between KPI reports from a firm rule: a cadence word, or an explicit number of days."""
    lower = text.lower()
    for word, days in _CADENCE_WORDS.items():
        if word in lower:
            return days
    m = re.search(r"(\d+)\s*days?", lower)
    return int(m.group(1)) if m and int(m.group(1)) > 0 else None


@register_watcher("kpi_overdue")
def kpi_overdue(db: Session, tenant_id: str) -> list[AlertDraft]:
    """Portfolio companies whose newest KPI observation is older than the firm's reporting cadence.
    Companies with no observations at all are not flagged: that is a setup gap, not a late report."""
    rule = fk.newest_accepted(db, tenant_id, "kpi_reporting_cadence")
    days = cadence_days(rule.value) if rule else None
    if days is None:
        return []
    out = []
    for co in db.query(PortfolioCompany).filter_by(tenant_id=tenant_id):
        obs = current_kpis(db, tenant_id, co.id)
        if not obs:
            continue
        newest = max(o.observed_at for o in obs)
        age = _age_days(newest)
        if age is None or age <= days:
            continue
        out.append(AlertDraft("kpi", "warning", f"{co.name}: no KPI update for {age} days (firm cadence {days} days)",
                              f"Firm rule (document {rule.document_id}, page {rule.page}): \"{rule.quote}\"",
                              f"kpi_overdue:{co.id}:{_week()}"))
    return out


def _week() -> str:
    return (datetime.now(UTC) - timedelta(days=datetime.now(UTC).weekday())).date().isoformat()


@register_watcher("firm_leverage_limit")
def firm_leverage_limit(db: Session, tenant_id: str) -> list[AlertDraft]:
    """Portfolio net leverage above the firm's accepted leverage_limit. The limit and its quote come
    from the firm profile, so the alert shows the rule it broke."""
    found = fk.limit(db, tenant_id, "leverage_limit")
    if found is None:
        return []
    cap, rule = found
    out = []
    for co in db.query(PortfolioCompany).filter_by(tenant_id=tenant_id):
        for o in current_kpis(db, tenant_id, co.id):
            if o.metric != "net_leverage_x" or o.unit != "x" or o.value <= cap:
                continue
            out.append(AlertDraft(
                "leverage", "critical",
                f"{co.name}: net leverage {o.value}x exceeds firm limit {cap}x ({o.period})",
                f"Firm rule (document {rule.document_id}, page {rule.page}): \"{rule.quote}\"",
                f"leverage:{co.id}:{o.period}:{o.value}:{cap}",
                [o.fact_id]))
    return out


@register_watcher("stalled_deals")
def stalled_deals(db: Session, tenant_id: str) -> list[AlertDraft]:
    """Live deals untouched for the firm's stall days. Re-alerts weekly while still stalled."""
    stall_days = _firm_days(db, tenant_id, "deal_stall_days", STALL_DAYS)
    out = []
    for d in db.query(Deal).filter_by(tenant_id=tenant_id):
        age = _age_days(d.updated_at)
        if d.stage in ("signed", "closed", "passed") or age is None or age < stall_days:
            continue
        out.append(AlertDraft("deal", "warning", f"{d.name}: no update for {age} days (stage {d.stage})",
                              f"Last change {d.updated_at}.", f"stalled:{d.id}:{_week()}"))
    return out


@register_watcher("overdue_dd")
def overdue_dd(db: Session, tenant_id: str) -> list[AlertDraft]:
    """Open DD requests unchanged for the firm's response days, one alert per deal per week."""
    response_days = _firm_days(db, tenant_id, "dd_response_days", DD_OPEN_DAYS)
    per_deal: dict[str, list[DDRequest]] = {}
    for r in db.query(DDRequest).filter_by(tenant_id=tenant_id, status="open"):
        age = _age_days(r.updated_at)
        if age is not None and age >= response_days:
            per_deal.setdefault(r.deal, []).append(r)
    return [AlertDraft("dd", "warning", f"{deal}: {len(rows)} DD request(s) open for {response_days}+ days",
                       "; ".join(f"{r.category}: {r.title}" for r in rows[:5]) + (" ..." if len(rows) > 5 else ""),
                       f"dd_overdue:{deal}:{_week()}") for deal, rows in per_deal.items()]


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


# Injected in tests; a failed fetch (network, rate limit, bad XML) skips that company for this scan only.
sec_fetch = secfeed.default_fetch


@register_watcher("sec_filings")
def sec_filings(db: Session, tenant_id: str) -> list[AlertDraft]:
    """New 10-K, 10-Q, 8-K and similar filings for targets marked `watching`, from each company's EDGAR feed.
    Keyed by accession number, so a filing alerts once and links to its archive index."""
    out = []
    for t in db.query(Target).filter_by(tenant_id=tenant_id, status="watching", source="sec"):
        try:
            entries = secfeed.parse_atom(sec_fetch(secfeed.feed_url(t.source_ref)).decode())
        except (OSError, ValueError):
            continue
        for e in entries:
            out.append(AlertDraft("filing", "info", f"{t.name}: new {e.form} filed {e.filed}",
                                  f"Filing index: {e.url}", f"filing:{e.accession}"))
    return out


_MIN_REVENUE = re.compile(r"min(?:imum)?\s+revenue\D{0,20}?(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)
_SECTORS = re.compile(r"sectors?\s*:\s*([^.;\n]+)", re.IGNORECASE)


def screening_criteria(text: str) -> Criteria:
    """Read the criteria a firm rule states in plain words: "sectors: software, fintech" and
    "minimum revenue 20000000". Anything the rule does not state stays unset and is not screened."""
    m = _MIN_REVENUE.search(text)
    s = _SECTORS.search(text)
    return Criteria(sectors=[x.strip() for x in s.group(1).split(",") if x.strip()] if s else [],
                    min_revenue=Decimal(m.group(1).replace(",", "")) if m else None)


@register_watcher("new_target_screen")
def new_target_screen(db: Session, tenant_id: str) -> list[AlertDraft]:
    """New targets that pass every criterion in the accepted deal_screening_criteria rule.
    Targets with unknown revenue are not alerted: the screen reports them as review, not match."""
    rule = fk.newest_accepted(db, tenant_id, "deal_screening_criteria")
    if rule is None:
        return []
    criteria = screening_criteria(rule.value)
    if not criteria.sectors and criteria.min_revenue is None:
        return []
    out = []
    for t in db.query(Target).filter_by(tenant_id=tenant_id, status="new"):
        if evaluate(t, criteria)["verdict"] != "match":
            continue
        out.append(AlertDraft("screening", "info", f"{t.name} matches the screening criteria",
                              f"Firm rule (document {rule.document_id}, page {rule.page}): \"{rule.quote}\". "
                              f"Source: {t.source_url or t.source_ref}", f"screen:{t.id}"))
    return out


def brief(db: Session, tenant_id: str, since: str) -> dict:
    """What the system raised since `since` (ISO timestamp), grouped for a reader: counts by kind and severity,
    then the critical and warning items first. Every item keeps its alert id and fact ids so it opens to sources."""
    rows = (db.query(Alert).filter_by(tenant_id=tenant_id)
            .filter(Alert.created_at >= since).order_by(Alert.id.desc()).all())
    rank = {s: i for i, s in enumerate(reversed(SEVERITIES))}
    by_kind: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for a in rows:
        by_kind[a.kind] = by_kind.get(a.kind, 0) + 1
        by_severity[a.severity] = by_severity.get(a.severity, 0) + 1
    top = sorted(rows, key=lambda a: (rank.get(a.severity, 9), -a.id))[:10]
    return {"since": since, "total": len(rows), "by_kind": by_kind, "by_severity": by_severity,
            "top": [alert_dict(a) for a in top]}
