import importlib.util
from pathlib import Path


def _mod():
    spec = importlib.util.spec_from_file_location("icm", Path(__file__).resolve().parents[1] / "scripts/ic_memo_sec.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def row(end, val, filed, form="10-K", fp="FY"):
    return {"end": end, "val": val, "filed": filed, "form": form, "fp": fp, "accn": "0000000001-00-000001"}


def test_annual_keeps_every_year_across_revenue_tags_and_latest_filing_wins():
    m = _mod()
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [row("2023-07-31", 100, "2023-09-01"), row("2023-07-31", 99, "2024-09-01"),
                                       row("2024-07-31", 150, "2024-09-01", form="10-Q", fp="Q1")]}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            row("2024-07-31", 160, "2024-09-01"), row("2025-07-31", 200, "2025-09-01")]}}}}}
    out = m.annual(facts, ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"))
    assert [(r["end"], r["val"]) for r in out] == [("2023-07-31", 99), ("2024-07-31", 160), ("2025-07-31", 200)]
