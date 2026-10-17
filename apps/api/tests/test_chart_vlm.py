import pytest

from app.parse import chart_vlm
from app.parse.charts import ChartValue

pytest.importorskip("pymupdf")


def ocr_label(value: float, bbox=(100.0, 100.0, 150.0, 120.0)) -> ChartValue:
    return ChartValue(2, f"{value:g}", value, bbox, 0.9)


def test_model_label_verified_by_ocr_keeps_bbox():
    out = chart_vlm.verify(["1,234"], [ocr_label(1234.0)], set(), page=2)
    assert len(out) == 1
    assert out[0].verified and out[0].source == "ocr"
    assert out[0].bbox == (100.0, 100.0, 150.0, 120.0)


def test_model_label_verified_by_page_text_has_no_bbox():
    out = chart_vlm.verify(["56.5"], [], {56.5}, page=2)
    assert out[0].verified and out[0].source == "page_text" and out[0].bbox is None


def test_model_label_without_match_stays_unverified():
    out = chart_vlm.verify(["999"], [ocr_label(1234.0)], {1.0}, page=2)
    assert len(out) == 1
    assert not out[0].verified and out[0].bbox is None and out[0].source is None


def test_non_numeric_and_duplicate_labels_are_dropped():
    out = chart_vlm.verify(["Revenue", "", "1,234", "1,234"], [ocr_label(1234.0)], set(), page=2)
    assert [v.text for v in out] == ["1,234"]


def test_vlm_disabled_without_flag(monkeypatch):
    monkeypatch.delenv("CHART_VLM", raising=False)
    monkeypatch.setenv("CHART_VLM_MODEL", "/nonexistent.gguf")
    assert not chart_vlm.vlm_enabled()
    assert chart_vlm.extract_vlm_values(None, 1) == []


@pytest.mark.skipif(not chart_vlm.vlm_enabled(), reason="needs CHART_VLM=1 and CHART_VLM_MODEL")
def test_vlm_bar_labels_verified_end_to_end(tmp_path, monkeypatch):
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pymupdf

    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)
    bars = ax.bar(["Q1", "Q2", "Q3"], [1234, 567, 890])
    ax.bar_label(bars, fmt="{:,.0f}", fontsize=14)
    ax.tick_params(labelsize=14)
    png = tmp_path / "chart.png"
    fig.savefig(png)
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(pymupdf.Rect(50, 50, 560, 400), filename=str(png))
    pdf = tmp_path / "chart.pdf"
    doc.save(pdf)

    # docling is too heavy for this job (torch wheels fill the runner disk), so the picture box is fixed:
    # the test PDF places the image at (50, 50, 560, 400)
    monkeypatch.setattr(chart_vlm, "chart_regions", lambda path, page: [(50.0, 50.0, 560.0, 400.0)])
    vals = chart_vlm.extract_vlm_values(pdf, 1)
    verified = {v.value for v in vals if v.verified}
    assert {1234.0, 567.0, 890.0} <= verified


def test_parse_labels_keeps_labels_from_a_reply_cut_off_mid_repeat():
    text = ':["12.5%","12.5","12.5","12.5","12.5","12.'
    assert chart_vlm.parse_labels(text) == ["12.5%", "12.5"]


def test_misread_label_not_on_chart_stays_unverified():
    # the model read "(3.25)" as -2.25; OCR reads -3.25 and -2.5, so -2.25 matches nothing
    ocr = [ocr_label(-3.25), ocr_label(-2.5)]
    out = chart_vlm.verify(["-2.25"], ocr, set(), page=2)
    assert len(out) == 1 and not out[0].verified and out[0].bbox is None


def test_empty_vlm_reply_falls_back_to_ocr_labels(tmp_path, monkeypatch):
    # The model returns nothing usable; OCR labels on the chart still come through, with their bbox.
    monkeypatch.setenv("CHART_VLM", "1")
    monkeypatch.setenv("CHART_VLM_MODEL", "x.gguf")
    monkeypatch.setattr(chart_vlm, "chart_regions", lambda path, page: [(0.0, 0.0, 10.0, 10.0)])
    monkeypatch.setattr(chart_vlm, "render_region", lambda path, page, box: __import__("PIL.Image", fromlist=["Image"]).new("RGB", (4, 4)))
    monkeypatch.setattr(chart_vlm, "read_region", lambda path, page, box: [ocr_label(120.0), ocr_label(80.0, (200.0, 100.0, 250.0, 120.0))])
    monkeypatch.setattr(chart_vlm, "ask_vlm", lambda png: [])
    monkeypatch.setattr(chart_vlm, "page_text_numbers", lambda path, page: set())
    out = chart_vlm.extract_vlm_values(tmp_path / "deck.pdf", 2)
    assert {v.value for v in out if v.verified and v.bbox} == {120.0, 80.0}
