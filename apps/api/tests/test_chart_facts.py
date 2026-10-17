import hashlib
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import SessionLocal, app
from app.models import Document, DocumentFile, PageRow
from app.parse import chart_vlm
from app.parse.chart_vlm import VlmValue
from app.rls import bind_tenant

pymupdf = pytest.importorskip("pymupdf")
c = TestClient(app)


def _pdf_bytes() -> bytes:
    doc = pymupdf.open()
    doc.new_page(width=612, height=792).insert_text((72, 72), "Revenue chart")
    return doc.tobytes()


def _doc_id(tenant_id: str) -> str:
    return hashlib.sha256(tenant_id.encode()).hexdigest()


def _seed(tenant_id: str) -> str:
    doc_id = _doc_id(tenant_id)
    with SessionLocal() as db:
        bind_tenant(db, tenant_id)
        db.add(Document(id=doc_id, tenant_id=tenant_id, sha256="c", filename="deck.pdf", n_pages=1, kind="pdf"))
        db.flush()
        db.add(PageRow(document_id=doc_id, number=1, text="Revenue chart 1,234 567 890"))
        db.add(DocumentFile(document_id=doc_id, tenant_id=tenant_id, data=_pdf_bytes()))
        db.commit()
    return doc_id


def _tenant():
    t = c.post("/admin/tenants", json={"name": "chart"}, headers={"X-Admin-Token": "test-admin"}).json()
    return t, {"Authorization": f"Bearer {t['api_key']}"}


def test_chart_values_enter_queue_as_ocr_unverified_with_bbox(monkeypatch):
    t, h = _tenant()
    doc = _seed(t["tenant_id"])
    monkeypatch.setattr(chart_vlm, "extract_vlm_values", lambda path, page: [
        VlmValue(1, "1,234", 1234.0, True, (100.0, 50.0, 150.0, 70.0), "ocr"),
        VlmValue(1, "567", 567.0, True, None, "page_text"),
        VlmValue(1, "999", 999.0, False, None, None),
        VlmValue(1, "890", 890.0, True, (200.0, 50.0, 250.0, 70.0), "ocr"),
    ])
    r = c.post(f"/documents/{doc}/chart-facts", params={"entity": "Acme", "period": "FY24"}, headers=h)
    assert r.status_code == 201
    body = r.json()
    assert len(body["created"]) == 2
    assert {s["reason"] for s in body["skipped"]} == {"matched page text only, no bbox to cite",
                                                       "not matched on the chart or page text"}
    queue = c.get("/facts", params={"status": "ocr_unverified"}, headers=h).json()
    by_value = {f["value"]: f for f in queue}
    assert set(by_value) == {"1234.000000", "890.000000"}
    src = by_value["1234.000000"]["sources"][0]
    assert src["page"] == 1 and src["quote"] == "1,234"
    assert c.get("/facts", params={"status": "verified"}, headers=h).json() == []


def test_chart_values_off_without_vision_model():
    t, h = _tenant()
    doc = _seed(t["tenant_id"])
    r = c.post(f"/documents/{doc}/chart-facts", params={"entity": "Acme", "period": "FY24"}, headers=h)
    assert r.status_code == 201
    assert r.json() == {"created": [], "skipped": []}


def test_chart_fact_rejects_label_that_is_not_the_value():
    from app.facts import CitationError, add_chart_fact

    t, _ = _tenant()
    doc = _seed(t["tenant_id"])
    with SessionLocal() as db, pytest.raises(CitationError):
        add_chart_fact(db, tenant_id=t["tenant_id"], entity="Acme", metric="chart value", period="FY24",
                       value=Decimal(999), unit="as printed", document_id=doc, page=1, label="1,234",
                       bbox=(0.0, 0.0, 1.0, 1.0))


@pytest.mark.skipif(not chart_vlm.vlm_enabled(), reason="needs CHART_VLM=1 and CHART_VLM_MODEL")
def test_synthetic_deck_bar_labels_reach_queue_end_to_end(tmp_path, monkeypatch):
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)
    bars = ax.bar(["Q1", "Q2", "Q3"], [1234, 567, 890])
    ax.bar_label(bars, fmt="{:,.0f}", fontsize=14)
    ax.tick_params(labelsize=14)
    png = tmp_path / "chart.png"
    fig.savefig(png)
    deck = pymupdf.open()
    page = deck.new_page(width=612, height=792)
    page.insert_text((50, 40), "Revenue by quarter")
    page.insert_image(pymupdf.Rect(50, 50, 560, 400), filename=str(png))
    deck_bytes = deck.tobytes()

    t, h = _tenant()
    with SessionLocal() as db:
        bind_tenant(db, t["tenant_id"])
        doc_id = _doc_id(t["tenant_id"])
        db.add(Document(id=doc_id, tenant_id=t["tenant_id"], sha256="d", filename="deck.pdf", n_pages=1, kind="pdf"))
        db.flush()
        db.add(PageRow(document_id=doc_id, number=1, text="Revenue by quarter"))
        db.add(DocumentFile(document_id=doc_id, tenant_id=t["tenant_id"], data=deck_bytes))
        db.commit()
    # docling is too heavy for this job, so the picture box is fixed to the one the deck places
    monkeypatch.setattr(chart_vlm, "chart_regions", lambda path, page: [(50.0, 50.0, 560.0, 400.0)])
    r = c.post(f"/documents/{doc_id}/chart-facts", params={"entity": "Acme", "period": "FY24"}, headers=h)
    assert r.status_code == 201
    values = {f["value"] for f in c.get("/facts", params={"status": "ocr_unverified"}, headers=h).json()}
    assert {"1234.000000", "567.000000", "890.000000"} <= values
    assert c.get("/facts", params={"status": "verified"}, headers=h).json() == []
