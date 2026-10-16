"""Background ingest: upload returns a job id at once; a small worker pool parses and stores.

- Bytes are spooled to SPOOL_DIR so queued jobs survive a restart (requeue_pending at startup).
- Unexpected failures retry up to MAX_ATTEMPTS; parse problems inside ingest_any are not failures,
  they come back as `skipped` entries in the result like the synchronous path.
- Optional malware scan: set SCAN_COMMAND (for example `clamdscan --no-summary`); the spooled file
  path is appended. Non-zero exit fails the job and deletes the spool file. Unset = no scan.
- The job carries the submitter's role and deal scope, so walls apply exactly as they do online.
"""
from __future__ import annotations

import json
import os
import secrets
import shlex
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.acl import Principal, parse_deals
from app.audit import log_event
from app.ingest import finalize_upload, ingest_any
from app.models import IngestJob, Tenant
from app.rls import bind_tenant

MAX_ATTEMPTS = 3
_active: set[str] = set()  # jobs running in this process (guards double execution)
_active_lock = threading.Lock()
SPOOL_DIR = Path(os.environ.get("SPOOL_DIR", str(Path(tempfile.gettempdir()) / "pe-spool")))
_pool = ThreadPoolExecutor(max_workers=int(os.environ.get("INGEST_WORKERS", "2")), thread_name_prefix="ingest")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def submit(db: Session, who: Principal, data: bytes, filename: str, deal: str | None,
           session_factory: sessionmaker) -> IngestJob:
    SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    jid = secrets.token_hex(12)
    path = SPOOL_DIR / jid
    path.write_bytes(data)
    job = IngestJob(id=jid, tenant_id=who.tenant, filename=filename, deal=deal, role=who.role,
                    scope=None if who.deals is None else ",".join(sorted(who.deals)), key_id=who.key_id,
                    spool_path=str(path), created_at=_now(), updated_at=_now())
    db.add(job)
    db.commit()
    _pool.submit(run_job, session_factory, jid, who.tenant)
    return job


def _scan(path: Path) -> str | None:
    cmd = os.environ.get("SCAN_COMMAND")
    if not cmd:
        return None
    try:
        r = subprocess.run([*shlex.split(cmd), str(path)], capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"scanner could not run: {e}"
    return None if r.returncode == 0 else f"malware scan failed: {(r.stdout + r.stderr).strip()[:300]}"


def run_job(session_factory: sessionmaker, job_id: str, tenant: str) -> None:
    with _active_lock:
        if job_id in _active:
            return  # already being worked on in this process
        _active.add(job_id)
    try:
        _run_job(session_factory, job_id, tenant)
    finally:
        with _active_lock:
            _active.discard(job_id)


def _run_job(session_factory: sessionmaker, job_id: str, tenant: str) -> None:
    with session_factory() as db:
        bind_tenant(db, tenant)
        # compare-and-set claim: only one runner can move queued -> running
        claimed = db.execute(update(IngestJob).where(IngestJob.id == job_id, IngestJob.status == "queued")
                             .values(status="running")).rowcount
        db.commit()
        job = db.get(IngestJob, job_id)
        if job is None or not claimed:
            return
        who = Principal(job.tenant_id, job.role, parse_deals(job.scope), job.key_id)
        for attempt in range(job.attempts + 1, MAX_ATTEMPTS + 1):
            job.status, job.attempts, job.stage, job.updated_at = "running", attempt, "scanning", _now()
            db.commit()
            path = Path(job.spool_path)
            try:
                bad = _scan(path)
                if bad:
                    _fail(db, job, bad)
                    return
                job.stage = "parsing"
                db.commit()
                res = ingest_any(db, job.tenant_id, path.read_bytes(), job.filename)
                job.stage = "tagging"
                db.commit()
                kept, skipped = finalize_upload(db, who, res, job.deal)
                for d in kept:
                    log_event(db, job.tenant_id, f"key:{job.key_id}", "document.upload",
                              {"document_id": d.id, "filename": d.filename, "deal": d.deal, "job": job.id})
                job.result = json.dumps({
                    "documents": [{"id": d.id, "filename": d.filename, "n_pages": d.n_pages, "kind": d.kind}
                                  for d in kept], "skipped": skipped})
                job.status, job.stage, job.error, job.updated_at = "done", "done", None, _now()
                db.commit()
                path.unlink(missing_ok=True)
                return
            except Exception as e:  # noqa: BLE001  retry unexpected failures, then fail loudly
                db.rollback()
                job = db.get(IngestJob, job_id)
                job.error, job.updated_at = f"attempt {attempt}: {e}", _now()
                db.commit()
        _fail(db, job, job.error or "failed")


def _fail(db: Session, job: IngestJob, reason: str) -> None:
    job.status, job.stage, job.error, job.updated_at = "failed", "failed", reason, _now()
    db.commit()
    Path(job.spool_path).unlink(missing_ok=True)


def requeue_pending(session_factory: sessionmaker) -> int:
    """Jobs left queued/running by a previous process go back to the pool. Walks tenants one by one
    because job rows are tenant-scoped under RLS (the tenant table itself is not)."""
    n = 0
    with session_factory() as db:
        tenants = [t.id for t in db.query(Tenant).all()]
    for tid in tenants:
        with session_factory() as db:
            bind_tenant(db, tid)
            for j in db.query(IngestJob).filter(IngestJob.status.in_(("queued", "running"))).all():
                with _active_lock:
                    busy = j.id in _active
                if busy or not Path(j.spool_path).exists():
                    continue
                if j.status == "running":  # left over from a dead process
                    j.status = "queued"
                    db.commit()
                _pool.submit(run_job, session_factory, j.id, tid)
                n += 1
    return n
