"""Figure detection: raster images are found per page with a top-left bbox; small ones are skipped."""
import pytest

from app.figures import detect_figures

pymupdf = pytest.importorskip("pymupdf")


def _pdf(tmp_path):
    from PIL import Image

    big = tmp_path / "chart.png"
    Image.new("RGB", (600, 300), "white").save(big)
    tiny = tmp_path / "logo.png"
    Image.new("RGB", (10, 10), "black").save(tiny)
    doc = pymupdf.open()
    p1 = doc.new_page(width=612, height=792)
    p1.insert_text((72, 60), "Revenue by quarter")
    p1.insert_image(pymupdf.Rect(72, 100, 472, 300), filename=str(big))
    p1.insert_image(pymupdf.Rect(500, 20, 510, 30), filename=str(tiny))
    doc.new_page(width=612, height=792).insert_text((72, 60), "no figures here")
    data = doc.tobytes()
    doc.close()
    return data


def test_large_image_is_found_with_its_page_and_top_left_bbox(tmp_path):
    figs = detect_figures(_pdf(tmp_path))
    assert [f.page for f in figs] == [1]
    left, top, right, bottom = figs[0].bbox
    assert figs[0].kind == "image"
    assert abs(left - 72) < 2 and abs(top - 100) < 2 and abs(right - 472) < 2 and abs(bottom - 300) < 2


def test_a_page_with_no_figures_yields_nothing(tmp_path):
    assert all(f.page != 2 for f in detect_figures(_pdf(tmp_path)))


def test_detect_and_list_over_the_api(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.helpers import new_tenant

    c = TestClient(app)
    h = new_tenant(c, "figs")
    doc_id = c.post("/documents", headers=h,
                    files={"file": ("deck.pdf", _pdf(tmp_path), "application/pdf")}).json()["id"]
    assert c.post(f"/documents/{doc_id}/figures/detect", headers=h).json() == {"document_id": doc_id, "found": 1}
    listed = c.get(f"/documents/{doc_id}/figures", headers=h).json()
    assert [(f["page"], f["kind"]) for f in listed] == [(1, "image")]
    # Running detection again replaces the rows rather than adding to them.
    c.post(f"/documents/{doc_id}/figures/detect", headers=h)
    assert len(c.get(f"/documents/{doc_id}/figures", headers=h).json()) == 1
    assert c.get(f"/documents/{doc_id}/figures", headers=new_tenant(c, "figs-other")).status_code == 404
