"""Score the legal extractor (rules) and the local-model second reader against hand-labelled gold. Usage:
  python evals/legal_benchmark.py --data DIR [--gold evals/legal_gold.json] [--no-reader] [--json out.json]
DIR holds the filed exhibits named <cik>_<accession>.htm. Per term: precision and recall. Value terms (governing law,
termination fee, non-solicit months) are right only when the normalised value matches gold; presence terms (escrow,
material adverse effect) are right when the presence matches. Combined = rules finding, else the reader's on the terms
the rules did not find."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))
from app import legal, legal_reader
from app.html_doc import parse_units

VALUE_TERMS = ("governing_law", "termination_fee", "non_solicit_months")
PRESENCE_TERMS = ("escrow", "material_adverse_effect")
NEW_VALUE_TERMS = ("termination_notice_days", "non_compete_months")  # lease and employment gold only
NEW_PRESENCE_TERMS = ("assignment", "change_of_control", "severance")
ALL_TERMS = VALUE_TERMS + PRESENCE_TERMS + NEW_VALUE_TERMS + NEW_PRESENCE_TERMS
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
         "ten": 10, "eleven": 11, "twelve": 12, "eighteen": 18, "twenty-four": 24, "thirty-six": 36}


def norm(term: str, value) -> str | None:
    if value in (None, "", False):
        return None
    s = str(value).strip().lower()
    if term == "governing_law":
        return re.sub(r"^state of\s+", "", s)
    if term == "termination_fee":
        digits = re.sub(r"[^\d.]", "", s).rstrip(".").split(".")[0]
        return digits or None
    if term == "non_solicit_months":
        return str(WORDS.get(s, s)).strip() if not s.isdigit() else str(int(s))
    return s


def prf(tp: int, fp: int, fn: int) -> tuple[float | None, float | None]:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    return p, r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--gold", default=str(Path(__file__).with_name("legal_gold.json")))
    ap.add_argument("--no-reader", action="store_true")
    ap.add_argument("--json")
    args = ap.parse_args()
    gold = {k: v for k, v in json.loads(Path(args.gold).read_text()).items() if not k.startswith("_")}
    llm = None
    if not args.no_reader:
        from app.llm import get_llm
        llm = get_llm()
    counts = {m: {t: [0, 0, 0] for t in ALL_TERMS} for m in ("rules", "reader", "combined")}
    rows = []
    for stem, g in gold.items():
        pages = [(u.idx + 1, u.text) for u in parse_units((Path(args.data) / f"{stem}.htm").read_bytes())]
        doc = g.get("doc_type", "spa")
        rules = legal.extract(pages, doc)
        first = {}
        for f in rules["findings"]:
            first.setdefault(f["term"], f)
        rd = {}
        if llm is not None:
            absent = [t for t in rules["absent"] if t in legal_reader.KEYWORDS]
            for f in legal_reader.read(pages, doc, absent, llm)["findings"]:
                rd.setdefault(f["term"], f)
        row = {"stem": stem}
        for t in [t for t in ALL_TERMS if t in VALUE_TERMS + PRESENCE_TERMS or t in g]:
            want = g.get(t)
            want = norm(t, want) if t in VALUE_TERMS + NEW_VALUE_TERMS else bool(want)
            got_r = first.get(t)
            got_d = rd.get(t)
            if t in PRESENCE_TERMS + NEW_PRESENCE_TERMS:
                pr, pd = (got_r is not None), (got_d is not None)
                pc = pr or pd
                preds = {"rules": pr, "reader": pd if not pr else None, "combined": pc}
                for m, p in preds.items():
                    if m == "reader" and llm is None:
                        continue
                    bucket = counts[m][t]
                    if p and want:
                        bucket[0] += 1
                    elif p and not want:
                        bucket[1] += 1
                    elif not p and want:
                        bucket[2] += 1
                row[t] = {"want": want, "rules": pr, "reader": pd}
            else:
                pr = norm(t, got_r["value"]) if got_r else None
                pd = norm(t, got_d["value"]) if got_d else None
                pc = pr if pr is not None else pd
                preds = {"rules": pr, "reader": pd if pr is None else None, "combined": pc}
                for m, p in preds.items():
                    if m == "reader" and llm is None:
                        continue
                    bucket = counts[m][t]
                    if p is not None and p == want:
                        bucket[0] += 1
                    elif p is not None:
                        bucket[1] += 1
                        if want is not None:
                            bucket[2] += 1
                    elif want is not None:
                        bucket[2] += 1
                row[t] = {"want": want, "rules": pr, "reader": pd}
        rows.append(row)
    print(f"{'term':26}{'mode':10}{'precision':>10}{'recall':>9}{'tp/fp/fn':>12}")
    for t in ALL_TERMS:
        if not any(sum(counts[m][t]) for m in counts):
            continue
        for m in ("rules", "reader", "combined"):
            if m == "reader" and llm is None:
                continue
            tp, fp, fn = counts[m][t]
            p, r = prf(tp, fp, fn)
            fmt = lambda x: "-" if x is None else f"{x:.2f}"
            print(f"{t:26}{m:10}{fmt(p):>10}{fmt(r):>9}{f'{tp}/{fp}/{fn}':>12}")
    if args.json:
        Path(args.json).write_text(json.dumps({"counts": counts, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
