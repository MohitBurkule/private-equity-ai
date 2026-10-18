"""10-K companyfacts -> ingest -> cited facts -> IC memo: every printed number must trace to its quote.

Runs the real ingest path of scripts/ic_memo_sec.py with a fake EDGAR client, offline and in memory.
Fails if a memo figure has no note, if a note's quote does not contain the figure, or if a memo line
lacks its [n] marker.
"""
import importlib.util
import re
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from app.citations import verify_number
from app.db import Base, make_engine
from app.facts import add_verified_fact
from app.ingest import _store_pages
from app.memo import build_memo_data
from app.models import Fact

ROOT = Path(__file__).resolve().parents[1]


def _icm():
    spec = importlib.util.spec_from_file_location("icm", ROOT / "scripts/ic_memo_sec.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _row(end, val, filed="2025-09-01"):
    return {"end": end, "val": val, "filed": filed, "form": "10-K", "fp": "FY", "accn": "0000000001-25-000001"}


class FakeEdgar:
    def fetch_companyfacts(self, cik):
        usd = lambda *rows: {"units": {"USD": list(rows)}}
        return {"entityName": "Acme Software Inc", "facts": {"us-gaap": {
            "Revenues": usd(_row("2023-07-31", 900), _row("2024-07-31", 1000), _row("2025-07-31", 1200)),
            "NetIncomeLoss": usd(_row("2024-07-31", -60), _row("2025-07-31", 150)),
        }}}


def test_every_memo_figure_traces_to_its_quote():
    icm = _icm()
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        entity = icm.ingest(db, "0000000001", FakeEdgar(), _store_pages, add_verified_fact, Decimal)
        db.commit()
        memo = build_memo_data(db, icm.TENANT, entity)
        facts = db.query(Fact).filter_by(tenant_id=icm.TENANT, entity=entity, status="verified").all()

        assert len(facts) == 5
        for f in facts:
            quote = f.sources[0].quote
            assert verify_number(f.value, quote), f"{f.metric} {f.period}: {f.value} not in quote {quote!r}"

        assert memo.lines, "memo has no figure lines"
        for line in memo.lines:
            assert re.search(r"\[\d+\]$", line), f"figure line without citation: {line!r}"
        for period_points in memo.series.values():
            for _, _, note in period_points:
                assert 1 <= note <= len(memo.notes), f"note {note} has no footnote"
