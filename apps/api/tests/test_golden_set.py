"""Gate on the hand-checked golden set. Scoring needs the source PDFs (data/sec, ~GB on the
shared mount) and runs too slowly for CI, so this checks the set itself: every item must be
citable, and every PDF source must name a page and the raw string the extractor is scored on.
Live accuracy stays in evals/run_golden_eval.py, run where the PDFs are present."""

import json
import re
from pathlib import Path

import pytest

from app.extract.tables import extract_rows

GOLDEN = Path(__file__).parent / "golden" / "golden_v1.jsonl"
ITEMS = [json.loads(line) for line in GOLDEN.open()]


def test_golden_set_has_all_hand_checked_items():
    assert len(ITEMS) == 18


@pytest.mark.parametrize("item", ITEMS, ids=lambda i: i["id"])
def test_item_is_citable(item):
    assert item["question"] and "answer_value" in item
    assert item["sources"], "every answer must cite at least one source"
    for src in item["sources"]:
        kind = src["type"]
        if kind == "pdf":
            # Narrative quotes (g18) carry no page; they must still carry the quoted text.
            assert src["doc"] and src["row_label"]
            assert src["pdf_page_1based"] is None or src["pdf_page_1based"] >= 1
            assert src["pdf_page_1based"] or src["raw"]
        elif kind == "xbrl":
            assert src["concept"] and src["accn"] and src["file"]
        elif kind in ("ixbrl", "html"):
            assert src["file"]
        else:
            pytest.fail(f"{item['id']}: unknown source type {kind!r}")


# Accuracy floor on the pdf rows whose page text is committed under tests/golden/pages.
# Pages are pre-extracted from the source PDFs (see tests/golden/pages/README.md). At this
# size one miss is 11%, so the floor is 0.95: any miss fails the build.
FLOOR = 0.95
PAGES = Path(__file__).parent / "golden" / "pages"


def _scored_rows():
    for item in ITEMS:
        for src in item["sources"]:
            if src["type"] != "pdf" or not (
                src.get("row_label") and src.get("raw") and src.get("pdf_page_1based")
            ):
                continue
            # Narrative and multi-token quotes are scored elsewhere; this floor covers numeric rows.
            if re.sub(r"[\d,.()\s]", "", src["raw"]):
                continue
            page = PAGES / f"{src['doc']}_p{src['pdf_page_1based']}.txt"
            if page.exists():
                yield item["id"], src, page


def test_extraction_accuracy_floor():
    total = found = 0
    misses = []
    for item_id, src, page in _scored_rows():
        rows = extract_rows(page.read_text(), src["pdf_page_1based"])
        want = _norm(src["row_label"])
        tokens = re.findall(r"\(?\d[\d,]*(?:\.\d+)?\)?", src["raw"])
        ok = any(
            want in _norm(r.label) and all(t in r.raw_values for t in tokens)
            for r in rows
        )
        total += 1
        found += ok
        if not ok:
            misses.append((item_id, src["row_label"], src["raw"]))
    assert total > 0, "no scorable golden rows; pages fixture missing?"
    assert found / total >= FLOOR, f"accuracy {found}/{total} below {FLOOR}: {misses}"


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
