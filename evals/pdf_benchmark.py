"""Benchmark PDF engines on the PDF-sourced golden items. Usage:
  python evals/pdf_benchmark.py --data /mnt/project-files/data [--engines a,b] [--json out.json]
Metrics per engine: page_recall (every expected number/keyword on the cited page), row_hit (all of them on ONE
line that also carries the row label: the table-row integrity PE numbers need), bbox_rate (hits that carry a
bbox for citation), seconds per page."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))
from app.parse import engines, router

# g13 cites 0-based pages (text is on 70/71, golden says 69/71); excluded rather than silently rescored.
KNOWN_GOLD_PAGE_ERRORS = {"g13"}
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def norm_words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def nums(s: str) -> list[str]:
    return [m.group().replace(",", "").rstrip(".") for m in NUM.finditer(s)]


def items(data: Path):
    gdir = data / "golden"
    out = []
    for l in (gdir / "golden_v1.jsonl").open():
        r = json.loads(l)
        if r["id"] in KNOWN_GOLD_PAGE_ERRORS:
            continue
        for s in r["sources"]:
            if s["type"] != "pdf" or not s.get("pdf_page_1based"):
                continue
            doc = s["doc"]
            f = data / ("uk/" + doc if doc.startswith("uk/") else f"sec/{doc}.pdf")
            if not f.exists():
                continue
            parts = [p.strip() for p in re.split(r";| / ", s["raw"])]
            labels = [p.strip() for p in re.split(r";| / ", s["row_label"])]
            if len(labels) != len(parts):
                labels = [""] * len(parts)
            out.append({"id": r["id"], "file": f, "page": s["pdf_page_1based"], "parts": list(zip(labels, parts)), "kind": "golden_v1"})
    for l in (gdir / "golden_sh01_v1.jsonl").open():
        r = json.loads(l)
        for s in r["sources"]:
            if s["type"] == "pdf-text" or s["type"] == "pdf-ocr" or s["type"].startswith("pdf"):
                f = data / s["file"]
                if f.exists():
                    # " ... " joins two cells that sit on different lines of the same form, so each side is its own part
                    out.append({"id": r["id"], "file": f, "page": s["page"], "parts": [("", " ".join(nums(q)) or q) for q in re.split(r";| \.\.\. ", s["quote"])], "kind": "sh01"})
    for l in (gdir / "golden_table_v1.jsonl").open():
        r = json.loads(l)
        f = data / f"sec/{r['doc']}.pdf"
        out.append({"id": r["id"], "file": f, "page": r["pdf_page_1based"], "parts": [(r["row_label"], r["raw"])], "kind": "table_v1"})
    return out


def part_hit(lines, label: str, raw: str):
    toks = nums(raw)
    words = [w for w in norm_words(raw) if not w.isdigit()] if not toks else []
    head = norm_words(label)[:3]
    page_ok = row_ok = False
    bbox = None
    page_nums = {n for ln in lines for n in nums(ln.text)}
    page_words = {w for ln in lines for w in norm_words(ln.text)}
    if toks:
        page_ok = all(t in page_nums for t in toks)
    else:
        page_ok = bool(words) and all(w in page_words for w in words)
    for ln in lines:
        lw = norm_words(ln.text)
        ln_n = set(nums(ln.text))
        if toks and not all(t in ln_n for t in toks):
            continue
        if words and not all(w in lw for w in words):
            continue
        if head and not all(w in lw for w in head):
            continue
        row_ok, bbox = True, ln.bbox
        break
    return page_ok, row_ok, bbox


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/mnt/project-files/data")
    ap.add_argument("--engines", default="")
    ap.add_argument("--json")
    a = ap.parse_args()
    data = Path(a.data)
    its = items(data)
    names = a.engines.split(",") if a.engines else engines.available()
    res = {}
    for e in names:
        agg = {"n": 0, "page": 0, "row": 0, "bbox": 0, "sec": 0.0, "pages": 0, "by_kind": {}, "fails": []}
        for it in its:
            t = time.time()
            try:
                if e == "router":
                    rp = router.route_page(it["file"], it["page"])
                    pr = engines.PageResult(e, it["page"], rp.lines)
                else:
                    pr = engines.run(e, it["file"], [it["page"]])[0]
            except Exception as ex:  # noqa: BLE001
                pr = engines.PageResult(e, it["page"], [])
                agg["fails"].append(f"{it['id']}:{type(ex).__name__}")
            agg["sec"] += time.time() - t
            agg["pages"] += 1
            ph = [part_hit(pr.lines, lb, rw) for lb, rw in it["parts"]]
            page_ok, row_ok = all(p[0] for p in ph), all(p[1] for p in ph)
            bb = row_ok and all(p[2] for p in ph)
            k = agg["by_kind"].setdefault(it["kind"], {"n": 0, "page": 0, "row": 0})
            for tgt in (agg, k):
                tgt["n"] += 1
                tgt["page"] += page_ok
                tgt["row"] += row_ok
            agg["bbox"] += bb
            if not row_ok:
                agg["fails"].append(f"{it['id']}@p{it['page']}")
        agg["sec_per_page"] = round(agg["sec"] / max(agg["pages"], 1), 3)
        res[e] = agg
        print(f"{e:18s} n={agg['n']} page={agg['page']} row={agg['row']} bbox={agg['bbox']} s/page={agg['sec_per_page']}  {agg['by_kind']}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
