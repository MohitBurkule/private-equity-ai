"""Enterprise value from a market-data feed, cited to the feed record it came from. The feed's rows are saved as a
CSV document (one row per security, as returned), so the fact's citation is that row and passes the same gate as any
other fact. Trading comps read `enterprise_value` facts, so a verified feed value feeds comps directly.

The feed shape is SYNTHETIC until the licence documentation is checked:
  GET {url} -> {"data": [{"id": str, "tev": number, "currency": str, "date": "YYYY-MM-DD"}]}
Nothing is defaulted: a missing field is dropped, and no usable row raises NoData."""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.comps import EV_METRIC
from app.facts import CitationError, add_verified_fact
from app.ingest import ingest_csv
from app.marketdata import NoData
from app.models import Fact

Fetch = Callable[[str, dict[str, str]], bytes]
COLUMNS = ["id", "tev", "currency", "date"]


def sync_tev(db: Session, tenant_id: str, *, entity: str, period: str, source: str, url: str, token: str,
             fetch: Fetch) -> Fact:
    if not url.startswith("https://"):
        raise NoData("feed url must be https")
    try:
        doc = json.loads(fetch(url, {"Authorization": f"Bearer {token}", "Accept": "application/json"}))
    except (OSError, ValueError) as e:  # unreachable host, HTTP error, bad URL or a body that is not JSON
        raise NoData(f"{source}: feed could not be read: {e}") from e
    rows = [r for r in (doc.get("data") or []) if r.get("tev") is not None and r.get("currency") and r.get("date")]
    if not rows:
        raise NoData(f"{source}: no enterprise value for {entity}")
    try:
        for r in rows:
            Decimal(str(r["tev"]))
    except InvalidOperation as e:
        raise NoData(f"{source}: tev is not a number") from e
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(COLUMNS)
    for r in rows:
        out.writerow([r.get("id", ""), r["tev"], r["currency"], r["date"]])
    record = ingest_csv(db, tenant_id, buf.getvalue().encode(), f"feed-{source}-{entity}.csv")
    # the latest dated row is the figure; its position in the CSV gives its citation line
    n = max(range(len(rows)), key=lambda i: str(rows[i]["date"]))
    prefix = f"row {n + 1}: "
    for page in record.pages:
        line = next((x for x in page.text.splitlines() if x.startswith(prefix)), None)
        if line is not None:
            break
    else:
        raise CitationError("feed row not found in its record")
    existing = [f for f in db.query(Fact).filter_by(tenant_id=tenant_id, entity=entity, metric=EV_METRIC,
                                                    period=period, status="verified")
                if any(s.document_id == record.id and s.quote == line for s in f.sources)]
    if existing:
        return existing[0]
    return add_verified_fact(db, tenant_id=tenant_id, entity=entity, metric=EV_METRIC, period=period,
                             value=Decimal(str(rows[n]["tev"])), unit=str(rows[n]["currency"]).upper(),
                             document_id=record.id, page=page.number, quote=line,
                             as_of=str(rows[n]["date"]))
