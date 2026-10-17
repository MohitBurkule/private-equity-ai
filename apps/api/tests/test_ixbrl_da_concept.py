"""Regression: total D&A is read from DepreciationAndAmortization (the income-statement and segment total),
not from the PP&E note's DepreciationDepletionAndAmortization (XPO FY2025: 521m total vs 467m PP&E only)."""
from types import SimpleNamespace

from app import ixbrl_facts
from app.ixbrl_full import Tagged

FY = "2025-01-01/2025-12-31"


def tag(name, text, row, period=FY, context="c-1", page=1):
    return Tagged(name=name, context=context, scale=6, text=text, page=page, row=row, period=period)


TAGS = [
    tag("us-gaap:Revenues", "8,157", "Total revenue 8,157"),
    tag("us-gaap:DepreciationDepletionAndAmortization", "467", "Depreciation of property and equipment 467",
        page=5),
    tag("us-gaap:DepreciationAndAmortization", "521", "Depreciation and amortization expense 521", page=9),
]


def run(monkeypatch, tags):
    saved = []

    def fake_add(db, **kw):
        saved.append(kw)
        return SimpleNamespace(id=len(saved))
    monkeypatch.setattr(ixbrl_facts, "add_verified_fact", fake_add)
    res = ixbrl_facts.extract(None, "t", "doc", "XPO", tags)
    return res, {c["metric"]: c for c in res["created"]}, saved


def test_total_da_wins_over_the_ppe_note_figure(monkeypatch):
    res, created, _ = run(monkeypatch, TAGS)
    da = created["depreciation_amortization"]
    assert da["value"] == "521000000" and da["concept"] == "DepreciationAndAmortization"
    assert da["quote"].startswith("Depreciation and amortization expense")
    assert res["period_end"] == "2025-12-31"


def test_falls_back_to_the_next_concept_when_total_is_not_tagged(monkeypatch):
    tags = [t for t in TAGS if "DepreciationAndAmortization" not in t.name]
    _, created, _ = run(monkeypatch, tags)
    assert created["depreciation_amortization"]["concept"] == "DepreciationDepletionAndAmortization"
    assert created["depreciation_amortization"]["value"] == "467000000"
