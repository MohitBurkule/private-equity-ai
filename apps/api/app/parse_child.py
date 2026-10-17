"""Parses one upload in a child process with a hard time limit.

The child only parses. It runs the ingest code against a scratch SQLite database in its own temp directory and
sends back plain rows. The parent writes every row to the tenant's database itself (store_parsed), so the child never
holds a tenant connection. A parse that runs past PARSE_TIMEOUT_S is killed; the caller fails the job without a retry.
PARSE_CHILD_DELAY_S is a test hook that makes the child sleep before it parses, to exercise the timeout.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import tempfile
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.ingest import IngestResult, ingest_any, tenant_doc_id
from app.models import Base, Document, DocumentFile, HtmlUnit, PageRow

CHILD_TENANT = "child"  # the scratch database belongs to no real tenant
DEFAULT_TIMEOUT_S = 120.0
ID_COLUMNS = {"id", "tenant_id"}  # the parent sets ids and the tenant on every row it writes


class ParseTimeout(Exception):
    """The child did not finish in time. The job fails; a parse that hangs once will hang again."""


def timeout_s() -> float:
    return float(os.environ.get("PARSE_TIMEOUT_S", DEFAULT_TIMEOUT_S))


def _row(obj: Any) -> dict:
    return {c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs if c.key not in ID_COLUMNS}


def _child(data: bytes, filename: str, conn: Any, scratch_dir: str) -> None:
    try:
        delay = float(os.environ.get("PARSE_CHILD_DELAY_S", "0"))
        if delay:
            time.sleep(delay)
        engine = create_engine(f"sqlite:///{scratch_dir}/scratch.db")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            def progress(done: int, total: int, name: str) -> None:
                conn.send(("progress", done, total, name))

            res = ingest_any(db, CHILD_TENANT, data, filename, progress=progress)
            docs = []
            for d in {x.id: x for x in res.documents}.values():
                docs.append({
                    "doc": _row(d),
                    "pages": [_row(p) for p in db.query(PageRow).filter_by(document_id=d.id).order_by(PageRow.id)],
                    "units": [_row(u) for u in db.query(HtmlUnit).filter_by(document_id=d.id)],
                    "files": [_row(f) for f in db.query(DocumentFile).filter_by(document_id=d.id)],
                })
            conn.send(("done", {"documents": docs, "skipped": res.skipped}))
        engine.dispose()
    except Exception as e:  # noqa: BLE001 - reported to the parent, which decides what the job does
        conn.send(("error", f"{type(e).__name__}: {e}"))
    finally:
        conn.close()


def parse_in_child(data: bytes, filename: str, progress: Callable[[int, int, str], None] | None = None,
                   limit: float | None = None) -> dict:
    """Runs the parse in a fresh process and returns its rows. Raises ParseTimeout past the limit."""
    limit = timeout_s() if limit is None else limit
    ctx = mp.get_context("spawn")  # a fresh interpreter: no locks or connections inherited from the server
    recv, send = ctx.Pipe(duplex=False)
    with tempfile.TemporaryDirectory() as scratch:
        proc = ctx.Process(target=_child, args=(data, filename, send, scratch), daemon=True)
        proc.start()
        send.close()
        deadline = time.monotonic() + limit
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ParseTimeout(f"parse timed out after {limit:g} s; the file was not stored")
                if not recv.poll(min(remaining, 0.2)):
                    if not proc.is_alive() and not recv.poll(0):
                        raise RuntimeError("parser exited without a result")
                    continue
                try:
                    kind, *rest = recv.recv()
                except EOFError:
                    raise RuntimeError("parser exited without a result") from None
                if kind == "progress" and progress is not None:
                    progress(*rest)
                elif kind == "done":
                    return rest[0]
                elif kind == "error":
                    raise RuntimeError(rest[0])
        finally:
            if proc.is_alive():
                proc.kill()
            proc.join()
            recv.close()


def store_parsed(db: Session, tenant_id: str, parsed: dict) -> IngestResult:
    """Writes the child's rows under the tenant. A document whose bytes are already stored is returned as is, the
    same as the in-process path. Ids are recomputed here, so the child never chooses one."""
    res = IngestResult()
    res.skipped = list(parsed["skipped"])
    try:
        for item in parsed["documents"]:
            d = item["doc"]
            doc_id = tenant_doc_id(tenant_id, d["sha256"])
            existing = db.get(Document, doc_id)
            if existing is not None:
                res.documents.append(existing)
                continue
            doc = Document(**{**d, "id": doc_id, "tenant_id": tenant_id})
            db.add(doc)
            db.add_all(PageRow(**{**p, "document_id": doc_id}) for p in item["pages"])
            db.add_all(HtmlUnit(**{**u, "tenant_id": tenant_id, "document_id": doc_id}) for u in item["units"])
            db.add_all(DocumentFile(**{**f, "tenant_id": tenant_id, "document_id": doc_id}) for f in item["files"])
            db.commit()
            res.documents.append(doc)
    except Exception:
        db.rollback()
        raise
    return res
