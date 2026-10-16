"""Email digest of alerts and the periodic scan. Recipients are given per call: tenant data is never
sent to an address configured globally."""
from __future__ import annotations

import os
import re
import logging
import smtplib
import threading
from datetime import UTC, datetime
from email.message import EmailMessage

from sqlalchemy.orm import Session, sessionmaker

from app.alerts import scan
from app.models import Alert, Tenant
from app.rls import bind_tenant

log = logging.getLogger(__name__)
_ADDR = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")


class MailNotConfigured(RuntimeError):
    pass


def render_digest(alerts: list[Alert]) -> tuple[str, str]:
    order = {"critical": 0, "warning": 1, "info": 2}
    rows = sorted(alerts, key=lambda a: (order.get(a.severity, 3), a.id))
    crit = sum(a.severity == "critical" for a in rows)
    subject = f"{len(rows)} new alert(s), {crit} critical"
    lines = [f"[{a.severity.upper()}] {a.title}\n    {a.detail}\n    sources: fact ids {a.fact_ids}" for a in rows]
    return subject, "\n\n".join(lines)


def send_email(to: list[str], subject: str, body: str) -> None:
    host = os.environ.get("SMTP_HOST")
    if not host:
        raise MailNotConfigured("set SMTP_HOST (and SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_FROM)")
    msg = EmailMessage()
    msg["Subject"], msg["To"] = subject, ", ".join(to)
    msg["From"] = os.environ.get("ALERT_EMAIL_FROM", "alerts@localhost")
    msg.set_content(body)
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=20) as s:
        if os.environ.get("SMTP_USER"):
            s.starttls()
            s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        s.send_message(msg)


def valid_recipients(to: list[str]) -> list[str]:
    out = [a.strip() for a in to if _ADDR.match(a.strip())]
    if not out or len(out) != len(to) or len(out) > 20:
        raise ValueError("recipients must be 1 to 20 valid email addresses")
    return out


def send_digest(db: Session, tenant_id: str, to: list[str]) -> int:
    """Email alerts not yet emailed; mark them. Returns how many were sent."""
    to = valid_recipients(to)
    pending = db.query(Alert).filter_by(tenant_id=tenant_id, emailed_at=None, status="new").order_by(Alert.id).all()
    if not pending:
        return 0
    subject, body = render_digest(pending)
    send_email(to, subject, body)  # raises before anything is marked
    now = datetime.now(UTC).isoformat(timespec="seconds")
    for a in pending:
        a.emailed_at = now
    db.commit()
    return len(pending)


def scan_all(session_factory: sessionmaker) -> dict[str, int]:
    """Run every watcher for every tenant. Used by the periodic thread and by tests."""
    with session_factory() as s:
        tenants = [t.id for t in s.query(Tenant).all()]
    out = {}
    for tid in tenants:
        with session_factory() as s:
            bind_tenant(s, tid)
            out[tid] = len(scan(s, tid))
    return out


def start_periodic_scan(session_factory: sessionmaker) -> threading.Event | None:
    """Starts a daemon thread when ALERT_SCAN_INTERVAL_S is set (seconds, at least 60)."""
    raw = os.environ.get("ALERT_SCAN_INTERVAL_S")
    if not raw:
        return None
    interval = max(60, int(raw))
    stop = threading.Event()

    def loop():
        while not stop.wait(interval):
            try:
                scan_all(session_factory)
            except Exception:  # noqa: BLE001  one bad tick must not kill the scheduler
                log.exception("periodic alert scan failed")

    threading.Thread(target=loop, name="alert-scan", daemon=True).start()
    return stop
