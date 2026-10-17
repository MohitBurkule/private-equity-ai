"""Score extraction on real investor decks with hand-labelled values (evals/golden/golden_real_decks_v1.jsonl).

Table rows: router route_page lines, each labelled row must carry all its printed numbers on one line.
Chart rows (kind chart_*): chart_vlm.extract_vlm_values with the hand-drawn chart box (points, PDF space).
Usage: python evals/real_deck_eval.py --data /mnt/project-files/data [--charts]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "apps" / "api"))

from pdf_benchmark import part_hit

from app.parse import router


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/mnt/project-files/data")
    ap.add_argument("--golden", default=str(ROOT / "evals" / "golden" / "golden_real_decks_v1.jsonl"))
    ap.add_argument("--charts", action="store_true")
    a = ap.parse_args()
    with open(a.golden) as fh:
        rows = [json.loads(l) for l in fh]
    tab = {"rows": 0, "row_hit": 0, "values": 0, "values_hit": 0, "misses": []}
    cht = {"values": 0, "landed_with_bbox": 0, "other_numbers_read": 0}
    for r in rows:
        f = Path(a.data) / (r["doc"] + ".pdf")
        if r["kind"].startswith("chart"):
            if not a.charts:
                continue
            from app.parse import chart_vlm
            box = tuple(r["chart_box_pt"])
            chart_vlm.chart_regions = lambda path, page, _b=box: [_b]
            truth = [float(x.strip("() ").replace(",", "")) * (-1 if "(" in x else 1) for x in r["raw"].split(";")]
            vals = chart_vlm.extract_vlm_values(f, r["pdf_page_1based"])
            landed = {round(v.value, 2) for v in vals if v.verified and v.bbox is not None}
            got = {round(v.value, 2) for v in vals}
            t = {round(x, 2) for x in truth}
            cht["values"] += len(t)
            cht["landed_with_bbox"] += len(landed & {round(abs(x), 2) for x in t} | landed & t)
            cht["other_numbers_read"] += len(got - {round(abs(x), 2) for x in t})
            continue
        lines = router.route_page(f, r["pdf_page_1based"]).lines
        parts = [x.strip() for x in r["raw"].split(";")]
        row_ok_all = True
        for part in parts:
            _, row_ok, _ = part_hit(lines, r["row_label"], part)
            tab["values"] += 1
            tab["values_hit"] += row_ok
            row_ok_all &= row_ok
            if not row_ok:
                tab["misses"].append(f"{r['id']}:{part}")
        tab["rows"] += 1
        tab["row_hit"] += row_ok_all
    print(json.dumps({"tables": tab, "charts": cht if a.charts else "skipped"}, indent=1))


if __name__ == "__main__":
    main()
