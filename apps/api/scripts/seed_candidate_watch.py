"""Create the demo weekly candidate_watch schedule for one tenant, mailing the Mailpit demo inbox.

Usage (from apps/api): DATABASE_URL=... python scripts/seed_candidate_watch.py <tenant_id> [recipient]
Mailpit receives mail on SMTP_HOST/SMTP_PORT (see workflows.smtp_mailer); this script only writes the schedule.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULT_RECIPIENT = "candidates@mailpit.local"


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: seed_candidate_watch.py <tenant_id> [recipient]", file=sys.stderr)
        return 2
    tenant = argv[0]
    recipient = argv[1] if len(argv) > 1 else os.environ.get("DEMO_RECIPIENT", DEFAULT_RECIPIENT)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from sqlalchemy.orm import sessionmaker

    from app import workflows as wf
    from app.db import make_engine
    from app.models import WorkflowSchedule
    from app.rls import bind_tenant

    engine = make_engine()
    with sessionmaker(bind=engine)() as s:
        bind_tenant(s, tenant)
        exists = s.query(WorkflowSchedule).filter_by(tenant_id=tenant, kind="candidate_watch").first()
        if exists:
            print(f"already scheduled: workflow {exists.id}")
            return 0
        w = wf.create(s, tenant, "Weekly new candidates", "candidate_watch", 7, {}, [recipient])
        print(f"created workflow {w.id} for {recipient}, every 7 days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
