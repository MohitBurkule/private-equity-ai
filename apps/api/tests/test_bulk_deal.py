"""Bulk move of documents between deals. Each document is checked on its own; a refused one never stops the rest."""
import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def _xlsx(label: str) -> bytes:
    wb = Workbook()
    wb.active["A1"] = label
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_bulk_move_moves_each_document_and_refuses_unknown_ones():
    h = new_tenant(c, "bulk1")
    for name in ("Alpha", "Beta"):
        assert c.post("/deals", headers=h, json={"name": name}).status_code == 201
    a = c.post("/documents", headers=h, data={"deal": "Alpha"},
               files={"file": ("a.xlsx", _xlsx("alpha-one"), "x")}).json()["id"]
    b = c.post("/documents", headers=h, files={"file": ("b.xlsx", _xlsx("beta-two"), "x")}).json()["id"]
    r = c.post("/documents/bulk-deal", headers=h, json={"doc_ids": [a, b, "nope"], "deal": "Beta"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert sorted(out["moved"]) == sorted([a, b])
    assert out["refused"] == [{"doc_id": "nope", "reason": "document not found"}]
    by_id = {d["id"]: d for d in c.get("/documents", headers=h).json()}
    assert by_id[a]["deal"] == "Beta" and by_id[b]["deal"] == "Beta"


def test_bulk_move_off_a_deal_and_size_limit():
    h = new_tenant(c, "bulk2")
    assert c.post("/deals", headers=h, json={"name": "Gamma"}).status_code == 201
    a = c.post("/documents", headers=h, data={"deal": "Gamma"},
               files={"file": ("g.xlsx", _xlsx("gamma"), "x")}).json()["id"]
    out = c.post("/documents/bulk-deal", headers=h, json={"doc_ids": [a], "deal": None}).json()
    assert out["moved"] == [a]
    by_id = {d["id"]: d for d in c.get("/documents", headers=h).json()}
    assert by_id[a]["deal"] in (None, "")
    assert c.post("/documents/bulk-deal", headers=h, json={"doc_ids": ["x"] * 201, "deal": None}).status_code == 422
