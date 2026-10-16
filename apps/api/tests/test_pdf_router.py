import pymupdf
import pytest

from app.parse import engines, router

pytestmark = pytest.mark.skipif("pymupdf" not in engines.available(), reason="pymupdf not installed")


def _pdf(tmp_path, rows, landscape=False):
    d = pymupdf.open()
    p = d.new_page(width=800 if landscape else 595, height=595 if landscape else 842)
    for i, (label, a, b) in enumerate(rows):
        y = 60 + i * 18
        p.insert_text((50, y), label, fontsize=10)
        p.insert_text((350, y), a, fontsize=10)
        p.insert_text((450, y), b, fontsize=10)
    f = tmp_path / "t.pdf"
    d.save(f)
    return f


def test_table_page_routed_verified_with_bbox(tmp_path):
    rows = [(f"Line item number {i}", f"{1000 + i:,}", f"({200 + i})") for i in range(8)]
    rp = router.route_page(_pdf(tmp_path, rows), 1)
    assert rp.kind == "table" and rp.verified and not rp.disputed
    c = router.cite(rp, "Line item number 3")
    assert c["page"] == 1 and c["bbox"] and c["verified"]


def test_blank_page_is_scanned(tmp_path):
    d = pymupdf.open()
    d.new_page()
    f = tmp_path / "b.pdf"
    d.save(f)
    assert router.route_page(f, 1, have={"pymupdf"}).kind == "scanned"


def test_disputed_numbers_flagged(tmp_path, monkeypatch):
    f = _pdf(tmp_path, [(f"Revenue item {i}", "1,577", "2,000") for i in range(8)])
    real = engines.run

    def fake(engine, path, pages):
        r = real(engine, path, pages)
        if engine != "pymupdf":
            r[0].lines = [engines.Line(ln.text.replace("1,577", "1,517"), None, engine) for ln in r[0].lines]
        return r
    monkeypatch.setattr(engines, "run", fake)
    rp = router.route_page(f, 1)
    assert "1577" in rp.disputed and not rp.verified
