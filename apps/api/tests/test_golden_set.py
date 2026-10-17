"""Gate on the hand-checked golden set. Scoring needs the source PDFs (data/sec, ~GB on the
shared mount) and runs too slowly for CI, so this checks the set itself: every item must be
citable, and every PDF source must name a page and the raw string the extractor is scored on.
Live accuracy stays in evals/run_golden_eval.py, run where the PDFs are present."""

import json
from pathlib import Path

import pytest

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
