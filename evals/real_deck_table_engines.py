"""Score table engines on the hand-labelled real-deck rows (golden_real_decks_v1, kind table).
Usage: python evals/real_deck_table_engines.py [--engines a,b] [--tol 0.5]
Engines: router (current), pymupdf, pdftotext_layout, pdfplumber, geo (pymupdf words grouped by y-overlap with tolerance --tol)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "apps" / "api"))

from pdf_benchmark import part_hit

from app.parse import engines, router

DATA = Path("/mnt/project-files/data")


def geo_lines(path: Path, page: int, tol: float):
    import pymupdf
    doc = pymupdf.open(str(path))
    words = [(w[0], w[1], w[2], w[3], w[4]) for w in doc[page - 1].get_text("words")]
    words.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows: list[list] = []
    for w in words:
        mid = (w[1] + w[3]) / 2
        if rows:
            ref = sorted((x[1] + x[3]) / 2 for x in rows[-1])
            med = ref[len(ref) // 2]
            h = max(w[3] - w[1], 1.0)
            if abs(mid - med) <= h * tol:
                rows[-1].append(w)
                continue
        rows.append([w])
    out = []
    for r in rows:
        r.sort(key=lambda w: w[0])
        out.append(engines.Line(" ".join(w[4] for w in r), None, "geo"))
    return out


def lines_for(engine: str, path: Path, page: int, tol: float):
    if engine == "router":
        return router.route_page(path, page).lines
    if engine == "geo":
        return geo_lines(path, page, tol)
    return engines.run(engine, path, [page])[0].lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", default="router,pymupdf,pdftotext_layout,pdfplumber,geo")
    ap.add_argument("--tol", type=float, default=0.5)
    ap.add_argument("--golden", default=str(ROOT / "evals" / "golden" / "golden_real_decks_v1.jsonl"))
    a = ap.parse_args()
    with open(a.golden) as fh:
        rows = [json.loads(l) for l in fh if '"table"' in l]
    for eng in a.engines.split(","):
        fallback_hits = 0
        vals = vals_hit = rows_ok = fallback_hits = 0
        for r in rows:
            f = DATA / (r["doc"] + ".pdf")
            lines = lines_for(eng, f, r["pdf_page_1based"], a.tol)
            ok_all = True
            for part in [x.strip() for x in r["raw"].split(";")]:
                _, ok, _ = part_hit(lines, r["row_label"], part)
                if not ok and eng == "router":
                    # fallback: the layout text, found by label; no bbox, so it is a text-only hit
                    ok = part_hit(lines_for("pdftotext_layout", f, r["pdf_page_1based"], a.tol), r["row_label"], part)[1]
                    fallback_hits += ok
                vals += 1
                vals_hit += ok
                ok_all &= ok
            rows_ok += ok_all
        extra = f" (+{fallback_hits} via layout fallback)" if eng == "router" else ""
        print(f"{eng:18s} values {vals_hit}/{vals}  rows {rows_ok}/{len(rows)}{extra}")


if __name__ == "__main__":
    main()
