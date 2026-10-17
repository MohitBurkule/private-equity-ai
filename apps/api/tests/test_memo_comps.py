import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def _seed(h, feed_name, rows):
    """rows: entity -> (ev or None, revenue). One workbook holds the figures; its file name is the feed's label."""
    wb = Workbook()
    for i, (ent, (ev, rev)) in enumerate(rows.items(), 1):
        wb.active[f"A{i}"], wb.active[f"B{i}"], wb.active[f"C{i}"] = ent, ev, rev
    b = io.BytesIO()
    wb.save(b)
    doc = c.post("/documents", files={"file": (feed_name, b.getvalue(), "x")}, headers=h).json()["id"]

    def fact(ent, metric, val, row, col):
        r = c.post("/facts", headers=h, json={"entity": ent, "metric": metric, "period": "FY24", "value": str(val),
                   "unit": "USD", "document_id": doc, "page": 1, "quote": f"Sheet!{col}{row}: {val:,}"})
        assert r.status_code == 201, r.text
    for i, (ent, (ev, rev)) in enumerate(rows.items(), 1):
        if ev is not None:
            fact(ent, "enterprise_value", ev, i, "B")
        fact(ent, "revenue", rev, i, "C")


def test_memo_comps_section_cites_each_peer_and_names_the_ev_feed():
    h = new_tenant(c, "memo-comps")
    _seed(h, "SYNTHETIC-feed-2026.xlsx", {"T": (None, 100), "P1": (1000, 200), "P2": (1500, 250),
                                          "P3": (900, 150), "P4": (None, 80)})
    md = c.get("/memo", params={"entity": "T", "peers": "P1,P2,P3,P4", "period": "FY24"}, headers=h).json()["markdown"]
    assert "Trading comps (peers, each cited):" in md
    assert "EV source: SYNTHETIC-feed-2026.xlsx" in md
    assert "EV/revenue 5.00x" in md  # P1: 1000 / 200
    assert "P4: no enterprise value fact, no multiple" in md
    assert "Peer median EV/revenue" in md
    assert "Sources:" in md and "[1]" in md


def test_memo_without_peers_has_no_comps_section():
    h = new_tenant(c, "memo-nocomps")
    _seed(h, "SYNTHETIC-feed-2026.xlsx", {"T": (None, 100), "P1": (1000, 200)})
    md = c.get("/memo", params={"entity": "T"}, headers=h).json()["markdown"]
    assert "Trading comps" not in md


def test_memo_docx_carries_the_comps_section():
    from docx import Document as Docx
    h = new_tenant(c, "memo-comps-docx")
    _seed(h, "SYNTHETIC-feed-2026.xlsx", {"T": (None, 100), "P1": (1000, 200), "P2": (1500, 250)})
    r = c.get("/memo.docx", params={"entity": "T", "peers": "P1,P2", "period": "FY24"}, headers=h)
    text = "\n".join(p.text for p in Docx(io.BytesIO(r.content)).paragraphs)
    assert "Trading comps (peers, each cited)" in text and "EV source: SYNTHETIC-feed-2026.xlsx" in text
