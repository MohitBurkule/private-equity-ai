"""Annual figures from a real companyfacts file (3M, /mnt/project-files/data/edgar). Skipped where the data is absent.

Two properties: a stub period filed inside a 10-K is not a full year, and when a year was filed more than once the
latest filing's value is the one kept (a restatement supersedes the earlier figure, it does not sit beside it)."""
import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = Path("/mnt/project-files/data/edgar/companyfacts_3M.json")


def _icm():
    spec = importlib.util.spec_from_file_location("icm", ROOT / "scripts/ic_memo_sec.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


needs_data = pytest.mark.skipif(not DATA.exists(), reason="real companyfacts file not present")


@needs_data
def test_annual_revenue_has_no_stub_period():
    m = _icm()
    facts = json.loads(DATA.read_text())
    rows = m.annual(facts, m.TAGS["revenue"])
    assert rows, "no annual revenue found"
    for r in rows:
        days = (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days
        assert 350 <= days <= 380, f"{r['end']} covers {days} days, not a year"


@needs_data
def test_annual_keeps_latest_filing_for_a_restated_year():
    m = _icm()
    facts = json.loads(DATA.read_text())
    rows = {r["end"]: r for r in m.annual(facts, m.TAGS["revenue"])}
    # FY2024 is filed in 2025 and again in 2026 (the later filing restates the same figure). The kept row is the 2026 one.
    assert rows["2024-12-31"]["filed"] == "2026-02-03"
    assert rows["2024-12-31"]["val"] == 24575000000
