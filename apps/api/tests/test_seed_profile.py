import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_seeded_values_quote_the_synthetic_document_verbatim():
    doc = (ROOT / "data/seed/synthetic_firm_strategy.txt").read_text()
    pages = doc.split("\f")
    seed = json.loads((ROOT / "data/seed/firm_profile.json").read_text())
    assert seed["accepted"] and seed["document"] == "synthetic_firm_strategy.txt"
    for row in seed["accepted"]:
        src = row["source"]
        assert "SYNTHETIC" not in row["value"]
        assert src["quote"] in pages[src["page"] - 1]
        assert all(n in src["quote"] for n in re.findall(r"\d+(?:\.\d+)?", row["value"]))
