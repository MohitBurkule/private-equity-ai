"""Peer enterprise values for the demo comps, SYNTHETIC: no real market prices are available offline.

  python scripts/seed_peer_ev_synthetic.py DATABASE_URL

The values are invented and the feed file is named SYNTHETIC_peer_tev.csv, so every comps cell that uses them says so.
Each EV is cited to its row in that CSV, like a feed record, so the same citation gate applies. Runs in-process
because the feed path needs a live https feed, which the demo does not have. Re-running adds nothing new.
"""
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.comps import EV_METRIC
from app.db import make_engine, make_session_factory
from app.facts import add_verified_fact
from app.ingest import ingest_csv
from app.models import Fact, Tenant

PERIOD = "FY2025"
# SYNTHETIC enterprise values in USD, one per peer. Not market data.
# Revenue is a SYNTHETIC peer input only where the demo has no FY2025 revenue fact for that peer (Hertz has a filing).
PEERS = [
    ("3M Company", 110_000_000_000, 24_600_000_000),
    ("Hertz Global Holdings", 13_000_000_000, None),
    ("Sotera Health Company", 6_000_000_000, 1_300_000_000),
]

csv_text = "id,tev,revenue,currency,date\n" + "".join(
    f"{e},{ev},{rev if rev is not None else ''},USD,2025-12-31\n" for e, ev, rev in PEERS)

Session = make_session_factory(make_engine(sys.argv[1]))
with Session() as db:
    tenant = db.query(Tenant).order_by(Tenant.id).first()
    record = ingest_csv(db, tenant.id, csv_text.encode(), "SYNTHETIC_peer_tev.csv")
    db.commit()
    for i, (entity, ev, rev) in enumerate(PEERS):
        prefix = f"row {i + 1}: "
        line = next((x for p in record.pages for x in p.text.splitlines() if x.startswith(prefix)), None)
        if line is None:
            raise SystemExit(f"SYNTHETIC peer row not found in its record: {entity}")
        page = next(p for p in record.pages if line in p.text)
        for metric, value in [(EV_METRIC, ev), ("revenue", rev)]:
            if value is None:
                continue
            if db.query(Fact).filter_by(tenant_id=tenant.id, entity=entity, metric=metric, period=PERIOD,
                                        status="verified").first():
                print(f"synthetic peer {metric} {entity}: already on file")
                continue
            add_verified_fact(db, tenant_id=tenant.id, entity=entity, metric=metric, period=PERIOD,
                              value=Decimal(value), unit="USD", document_id=record.id, page=page.number, quote=line)
            print(f"synthetic peer {metric} {entity}: ok")
    db.commit()
