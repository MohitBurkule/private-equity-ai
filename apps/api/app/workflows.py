"""Scheduled workflows: run a portfolio report or comps on a cadence and email a short summary.

Runs only when called (`run_due`, from `POST /workflows/run-due` or a cron hitting it), so there is no hidden
background thread. Every run uses the schedule owner's tenant and the visibility the caller of run-due has.
A failed run is recorded with its error and rescheduled; the summary lists only cited, code-computed items.
Mail goes through SMTP when SMTP_HOST is set; otherwise the result stays in `last_result` (the outbox).
"""
from __future__ import annotations

import json
import os
import smtplib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app import comps as comps_mod
from app.models import Alert, WorkflowSchedule
from app.report import build_report

KINDS = ("portfolio_report", "comps", "alert_digest")
Mailer = Callable[[list[str], str, str], None]


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def create(db: Session, tenant: str, name: str, kind: str, every_days: int, params: dict | None,
           recipients: list[str], start: datetime | None = None) -> WorkflowSchedule:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if not 1 <= every_days <= 366:
        raise ValueError("every_days must be 1..366")
    if any("@" not in r or "\n" in r or "," in r for r in recipients):
        raise ValueError("invalid recipient")
    w = WorkflowSchedule(tenant_id=tenant, name=name, kind=kind, params=json.dumps(params or {}),
                         every_days=every_days, recipients=",".join(recipients),
                         next_run=_iso(start or _now()))
    db.add(w)
    db.commit()
    return w


ORDER = {"critical": 0, "warning": 1, "info": 2}


def _summary(kind: str, result: dict) -> str:
    if kind == "alert_digest":
        return "\n\n".join(f"[{a['severity'].upper()}] {a['title']}\n    {a['detail']}" for a in result["alerts"])
    if kind == "portfolio_report":
        lines = [f"Breaches: {len(result.get('breaches', []))}"]
        for b in result.get("breaches", []):
            lines.append(f"- {b}")
        for co in result.get("companies", []):
            lines.append(f"{co['name']}: {len(co.get('kpis', []))} KPIs with sources")
        return "\n".join(lines)
    lines = [f"Comps for {result['target']} ({result['period']})"]
    for im in result["implied"]:
        lines.append(f"- {im['multiple']}: " + (f"{im['low']} to {im['high']} (mid {im['mid']})"
                                                if im.get("mid") else im.get("note", "no range")))
    return "\n".join(lines)


def _alert_digest(db: Session, w: WorkflowSchedule) -> dict:
    """Alerts still open that were raised since the previous run (or the last cadence window on the first run)."""
    since = w.last_run or _iso(_now() - timedelta(days=w.every_days))
    rows = (db.query(Alert).filter_by(tenant_id=w.tenant_id, status="new")
            .filter(Alert.created_at >= since).all())
    rows.sort(key=lambda a: (ORDER.get(a.severity, 3), a.id))
    return {"alerts": [{"id": a.id, "severity": a.severity, "title": a.title, "detail": a.detail} for a in rows]}


def _execute(db: Session, w: WorkflowSchedule, scope: set[str] | None) -> dict:
    p = json.loads(w.params)
    if w.kind == "alert_digest":
        return _alert_digest(db, w)
    if w.kind == "portfolio_report":
        return build_report(db, w.tenant_id, scope)
    return comps_mod.run(db, w.tenant_id, p["target"], p["peers"], p["period"], p.get("metrics", ["revenue", "ebitda"]),
                         scope)


def run_due(db: Session, tenant: str, scope: set[str] | None, mailer: Mailer | None = None,
            now: datetime | None = None) -> list[dict]:
    now = now or _now()
    out = []
    due = (db.query(WorkflowSchedule).filter_by(tenant_id=tenant, active=1)
           .filter(WorkflowSchedule.next_run <= _iso(now)).order_by(WorkflowSchedule.id).all())
    for w in due:
        try:
            result = _execute(db, w, scope)
            body = _summary(w.kind, result)
            w.last_status, w.last_result = "ok", json.dumps({"summary": body, "result": result}, default=str)
            if mailer and w.recipients and (w.kind != "alert_digest" or result["alerts"]):
                mailer(w.recipients.split(","), f"[{w.name}] scheduled update", body)  # no mail for an empty digest
        except Exception as e:  # noqa: BLE001  recorded, never raised: one bad schedule must not stop the others
            w.last_status, w.last_result = "failed", f"{type(e).__name__}: {e}"
        w.last_run = _iso(now)
        w.next_run = _iso(now + timedelta(days=w.every_days))
        out.append({"id": w.id, "name": w.name, "status": w.last_status})
    db.commit()
    return out


def smtp_mailer() -> Mailer | None:
    host = os.environ.get("SMTP_HOST")
    if not host:
        return None

    def send(to: list[str], subject: str, body: str) -> None:
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = os.environ.get("SMTP_FROM", "pe-platform@localhost"), ", ".join(to), subject
        m.set_content(body)
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=20) as s:
            if os.environ.get("SMTP_USER"):
                s.starttls()
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            s.send_message(m)
    return send
