"""SYNTHETIC investor deck and CIM, built with known values, to measure how many table and chart values come
out right. Every page is labelled SYNTHETIC. Nothing here is real company data.

  python evals/synthetic_deck_eval.py --out /mnt/project-files/data/synthetic [--charts]

Tables are scored on the text layer with the same row test as evals/pdf_benchmark.py. Charts are scored with the
chart model (CHART_VLM=1 and CHART_VLM_MODEL/CHART_VLM_MMPROJ set): a value counts as landed when the model reads
it, verifies it on the chart, and the chart reader gives it a bbox to cite. Output is JSON on stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "evals"))

from pdf_benchmark import part_hit

# Ground truth, all invented. Each chart value is printed on the chart, and each table value is on the page text.
TABLE_ROWS = [
    ("Revenue", ["$412.5", "$468.9", "$531.0"]),
    ("Gross profit", ["$247.5", "$290.7", "$333.5"]),
    ("Adjusted EBITDA", ["$84.2", "$103.1", "$125.8"]),
    ("Capital expenditure", ["(21.4)", "(24.0)", "(27.6)"]),
]
STACK = {"Segment A": [120, 150, 180], "Segment B": [80, 95, 110]}
YEARS = ["FY22", "FY23", "FY24"]
LINE = [12.5, 14.0, 15.5]


def table_page(doc: pymupdf.Document, title: str) -> None:
    page = doc.new_page(width=612, height=792)
    page.insert_text((50, 40), f"SYNTHETIC: {title}", fontsize=12)
    page.insert_text((50, 70), "USD millions", fontsize=10)
    y = 100
    page.insert_text((50, y), "Metric                   FY22        FY23        FY24", fontsize=10)
    for label, vals in TABLE_ROWS:
        y += 18
        cells = "".join(f"{v:<12}" for v in vals)
        page.insert_text((50, y), f"{label:<24}{cells}", fontsize=10)


def stack_chart(path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)
    bottom = [0, 0, 0]
    for name, vals in STACK.items():
        bars = ax.bar(YEARS, vals, bottom=bottom, label=name)
        ax.bar_label(bars, fmt="{:,.0f}", label_type="center", fontsize=12)
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax.tick_params(labelsize=12)
    ax.legend(fontsize=10)
    fig.savefig(path)
    plt.close(fig)


def line_chart(path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)
    ax.plot(YEARS, LINE, marker="o")
    for x, y in zip(YEARS, LINE):
        ax.annotate(f"{y:.1f}%", (x, y), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=12)
    ax.tick_params(labelsize=12)
    fig.savefig(path)
    plt.close(fig)


def chart_page(doc: pymupdf.Document, title: str, img: Path) -> None:
    page = doc.new_page(width=612, height=792)
    page.insert_text((50, 40), f"SYNTHETIC: {title}", fontsize=12)
    page.insert_image(pymupdf.Rect(50, 60, 560, 400), filename=str(img))


def build(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    stack_chart(out / "stack.png")
    line_chart(out / "line.png")
    deck = pymupdf.open()
    table_page(deck, "investor deck, financial summary")
    chart_page(deck, "investor deck, revenue by segment", out / "stack.png")
    chart_page(deck, "investor deck, adjusted EBITDA margin", out / "line.png")
    deck.save(out / "synthetic_investor_deck.pdf")
    cim = pymupdf.open()
    table_page(cim, "CIM, historical summary")
    chart_page(cim, "CIM, segment revenue", out / "stack.png")
    cim.save(out / "synthetic_cim.pdf")
    return {"deck": str(out / "synthetic_investor_deck.pdf"), "cim": str(out / "synthetic_cim.pdf")}


def score_tables(pdf: Path, page_no: int, engine: str = "router") -> dict:
    from app.parse import engines, router

    if engine == "router":
        lines = router.route_page(pdf, page_no).lines
    else:
        lines = engines.run(engine, pdf, [page_no])[0].lines
    hits = 0
    total = 0
    for label, vals in TABLE_ROWS:
        for v in vals:
            total += 1
            _, row_ok, _ = part_hit(lines, label, v)
            hits += bool(row_ok)
    return {"values": total, "row_hit": hits}


def score_charts(pdf: Path, page_no: int, truth: list[float]) -> dict:
    from app.parse import chart_vlm

    box = (50.0, 60.0, 560.0, 400.0)
    chart_vlm.chart_regions = lambda path, page: [box]  # docling is not in this job; the picture box is known
    vals = chart_vlm.extract_vlm_values(pdf, page_no)
    landed = {round(v.value, 2) for v in vals if v.verified and v.bbox is not None}
    got = {round(v.value, 2) for v in vals}
    return {
        "truth": len(truth),
        "landed_with_bbox": len(landed & {round(t, 2) for t in truth}),
        "read_but_not_landed": len((got - landed) & {round(t, 2) for t in truth}),
        "other_numbers_read": len(got - {round(t, 2) for t in truth}),  # axis ticks and other printed numbers, not truth misses
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/mnt/project-files/data/synthetic")
    ap.add_argument("--charts", action="store_true")
    a = ap.parse_args()
    paths = build(Path(a.out))
    res: dict = {"synthetic": True, "files": paths}
    res["tables_deck_p1"] = score_tables(Path(paths["deck"]), 1)
    res["tables_cim_p1"] = score_tables(Path(paths["cim"]), 1)
    if a.charts:
        stack_truth = [v for vals in STACK.values() for v in vals]
        res["chart_stack"] = score_charts(Path(paths["deck"]), 2, stack_truth)
        res["chart_line"] = score_charts(Path(paths["deck"]), 3, LINE)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
