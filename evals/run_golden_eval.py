"""Row-extraction eval on golden_v1: does extract_rows find the gold row/raw string on the gold page?

Reports found / total and each miss. Usage: python evals/run_golden_eval.py DATA_DIR
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.extract.tables import extract_rows  # noqa: E402
from app.parse.pdf import extract_pages  # noqa: E402


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def main(data: Path) -> dict:
    items = [json.loads(x) for x in (data / "golden" / "golden_v1.jsonl").open()]
    cache: dict[str, list] = {}
    total = found = 0
    misses, skipped = [], []
    for it in items:
        for s in it["sources"]:
            if s.get("type") != "pdf" or not (s.get("row_label") and s.get("raw") and s.get("pdf_page_1based")):
                continue
            path = data / "sec" / f"{s['doc']}.pdf"
            if not path.exists():
                continue
            pages = cache.setdefault(s["doc"], extract_pages(path))
            rows = extract_rows(pages[s["pdf_page_1based"] - 1].text, s["pdf_page_1based"])
            total += 1
            want = norm(s["row_label"])
            toks = re.findall(r"\(?\d[\d,]*(?:\.\d+)?\)?", s["raw"])
            if re.sub(r"[\d,.()\s]", "", s["raw"]):  # not a plain numeric row (narrative or multi-row)
                skipped.append(it["id"])
                total -= 1
                continue
            ok = any(want in norm(r.label) and all(t in r.raw_values for t in toks) for r in rows)
            found += ok
            if not ok:
                misses.append({"id": it["id"], "label": s["row_label"], "raw": s["raw"]})
    out = {"total": total, "found": found, "rate": round(found / total, 3) if total else None,
           "skipped_non_numeric": skipped, "misses": misses}
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main(Path(sys.argv[1]))
