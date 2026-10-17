"""SYNTHETIC peer comps for the demo: enterprise value and FY2025 revenue for three invented peers.

  python scripts/seed_peer_ev_synthetic.py DATABASE_URL

No real market prices or peer financials are available offline, so the peers are named "SYNTHETIC Peer A/B/C"
and every figure is invented. Real company names are never given invented numbers. Each figure is cited to its row
in SYNTHETIC_peer_tev.csv, so the same citation gate applies. Runs in-process because the feed path needs a live
https feed the demo cannot reach. Re-running adds nothing new.
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
# (name, EV, FY2025 revenue, FY2025 EBITDA), USD. Invented; not market data.
PEERS = [
    ("SYNTHETIC Peer A", 9_000_000_000, 4_000_000_000, 900_000_000),
    ("SYNTHETIC Peer B", 15_000_000_000, 6_000_000_000, 1_500_000_000),
    ("SYNTHETIC Peer C", 5_000_000_000, 2_000_000_000, 500_000_000),
]

csv_text = "id,tev,revenue,ebitda,currency,date\n" + "".join(
    f"{name},{ev},{rev},{ebitda},USD,2025-12-31\n" for name, ev, rev, ebitda in PEERS)

Session = make_session_factory(make_engine(sys.argv[1]))
with Session() as db:
    tenant = db.query(Tenant).order_by(Tenant.id).first()
    record = ingest_csv(db, tenant.id, csv_text.encode(), "SYNTHETIC_peer_tev.csv")
    db.commit()
    for i, (name, ev, rev, ebitda) in enumerate(PEERS):
        prefix = f"row {i + 1}: "
        line = next((x for p in record.pages for x in p.text.splitlines() if x.startswith(prefix)), None)
        if line is None:
            raise SystemExit(f"SYNTHETIC peer row not found in its record: {name}")
        page = next(p for p in record.pages if line in p.text)
        for metric, value in [(EV_METRIC, ev), ("revenue", rev), ("ebitda", ebitda)]:
            if (db.query(Fact).filter_by(tenant_id=tenant.id, entity=name, metric=metric, period=PERIOD,
                                         status="verified").first()):
                print(f"synthetic peer {metric} {name}: already on file")
                continue
            add_verified_fact(db, tenant_id=tenant.id, entity=name, metric=metric, period=PERIOD,
                              value=Decimal(value), unit="USD", document_id=record.id, page=page.number, quote=line)
            print(f"synthetic peer {metric} {name}: ok")
    db.commit()
