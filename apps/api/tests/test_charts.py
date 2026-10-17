import pytest
from app.parse import charts

pytest.importorskip("pymupdf")
pytest.importorskip("docling")


def test_parse_number_accepts_printed_labels_only():
    assert charts.parse_number("1,234") == 1234.0
    assert charts.parse_number("(56.5)") == -56.5
    assert charts.parse_number("12%") == 12.0
    assert charts.parse_number("Revenue") is None
    assert charts.parse_number("") is None


def test_chart_labels_recovered_with_bbox(tmp_path):
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

    vals = charts.extract_chart_values(pdf, 1)
    found = {v.value for v in vals}
    assert {1234.0, 567.0, 890.0} <= found
    hit = next(v for v in vals if v.value == 1234.0)
    x0, y0, x1, y1 = hit.bbox
    assert 50 <= x0 and x1 <= 560 and 50 <= y0 and y1 <= 400
