"""After a restore: count rows and verify every tenant's audit hash chain. Exit 1 on any problem.

Run as a superuser/BYPASSRLS role (RLS is forced for owners), so every query filters by tenant_id itself.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from sqlalchemy import func, select, text  # noqa: E402

from app.audit import verify_chain  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import Document, Fact, Tenant  # noqa: E402
from app.rls import bind_tenant  # noqa: E402


def main() -> int:
    engine = make_engine(os.environ["RESTORE_CHECK_URL"])
    Session = make_session_factory(engine)
    bad = 0
    with Session() as db:
        tenants = [t.id for t in db.scalars(select(Tenant))]
    print(f"tenants: {len(tenants)}")
    for tid in tenants:
        with Session() as db:
            bind_tenant(db, tid)
            docs = db.scalar(select(func.count()).select_from(Document).where(Document.tenant_id == tid))
            facts = db.scalar(select(func.count()).select_from(Fact).where(Fact.tenant_id == tid))
            orphans = db.execute(text(
                "SELECT count(*) FROM fact_source s JOIN fact f ON f.id = s.fact_id LEFT JOIN document d "
                "ON d.id = s.document_id WHERE f.tenant_id = :t AND d.id IS NULL"), {"t": tid}).scalar()
            ok, first_bad = verify_chain(db, tid)
            print(f"  {tid}: documents={docs} facts={facts} orphan_sources={orphans} audit_chain_ok={ok}")
            if not ok or orphans:
                bad += 1
                print(f"  PROBLEM in {tid}: first_bad_audit_id={first_bad} orphan_sources={orphans}")
    print("restore check:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
