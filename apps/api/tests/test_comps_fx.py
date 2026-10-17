"""Comps FX: a peer whose metric is in another currency is converted at the ECB rate, and the rate, its date
and source are shown on that row. SYNTHETIC deal facts; the ECB body is the saved real snapshot."""
import io
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app, get_market_fetch
from tests.helpers import new_tenant

c = TestClient(app)
ECB = (Path(__file__).parent / "fixtures" / "macro" / "ecb_exr_usd_eur.xml").read_bytes()


def _doc(h):
    wb = Workbook()
    for r, (ent, ev, e) in enumerate([("P1", 1000, 100), ("P2", 1200, 100), ("T", None, 50)], 1):
        wb.active[f"A{r}"] = ent
        if ev is not None:
            wb.active[f"B{r}"] = ev
        wb.active[f"C{r}"] = e
    b = io.BytesIO()
    wb.save(b)
    return c.post("/documents", files={"file": ("m.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]


def _fact(h, doc, ent, metric, val, unit, quote):
    r = c.post("/facts", headers=h, json={"entity": ent, "metric": metric, "period": "FY24", "value": str(val),
                                          "unit": unit, "document_id": doc, "page": 1, "quote": quote})
    assert r.status_code == 201, r.text


def _setup(h):
    doc = _doc(h)
    _fact(h, doc, "P1", "enterprise_value", 1000, "EUR", "Sheet!B1: 1,000")
    _fact(h, doc, "P1", "ebitda", 100, "USD", "Sheet!C1: 100")
    _fact(h, doc, "P2", "enterprise_value", 1200, "EUR", "Sheet!B2: 1,200")
    _fact(h, doc, "P2", "ebitda", 100, "EUR", "Sheet!C2: 100")
    _fact(h, doc, "T", "ebitda", 50, "EUR", "Sheet!C3: 50")


def _comps(fetch):
    app.dependency_overrides[get_market_fetch] = lambda: fetch
    try:
        h = new_tenant(c, "comps-fx")
        _setup(h)
        return c.post("/calc/comps", json={"target": "T", "peers": ["P1", "P2"], "period": "FY24",
                                           "metrics": ["ebitda"]}, headers=h).json()
    finally:
        app.dependency_overrides.pop(get_market_fetch, None)


def test_usd_peer_metric_converted_to_eur_with_cited_rate():
    out = _comps(lambda u, h: ECB)
    p1 = next(p for p in out["peers"] if p["entity"] == "P1")
    # EV 1000 EUR / (100 USD x 1.1253 EUR per USD) = 8.89
    assert p1["multiples"]["ebitda"] == "8.89"
    assert p1["fx"]["ebitda"] == {"from": "USD", "to": "EUR", "rate": "1.1253", "as_of": "2026-10-16", "source": "ecb"}
    p2 = next(p for p in out["peers"] if p["entity"] == "P2")
    assert p2["fx"] == {} and p2["multiples"]["ebitda"] == "12.00"  # same currency: no conversion


def test_unreachable_rate_source_marks_row_not_meaningful():
    def down(u, h):
        raise OSError("timeout")
    out = _comps(down)
    p1 = next(p for p in out["peers"] if p["entity"] == "P1")
    assert p1["multiples"]["ebitda"] is None and "no FX rate USD to EUR" in p1["nm"]["ebitda"]
