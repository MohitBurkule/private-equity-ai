"""Verified facts from a tagged 10-K (inline XBRL), without an LLM.

Each headline figure is read from the filing's own tag for the latest full fiscal year (a 12-month, non-dimensional
period). It becomes a fact only through add_verified_fact, so the citation gate applies: the quote (the table row the
figure sits in) must be on the cited page and the printed number must match the tagged value after its scale. A figure
that fails the gate is listed under rejected with the reason, never stored.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.facts import CitationError, add_verified_fact
from app.ixbrl_full import Tagged

BALANCE = {"total_assets"}  # instants, not durations
# metric name -> us-gaap concepts, first match wins
CONCEPTS = {
    "revenue": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "total_assets": ("Assets",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "depreciation_amortization": ("DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
                                  "DepreciationAndAmortization"),
}


def _days(period: str) -> int:
    start, end = period.split("/")
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def latest_fiscal_year(tags: list[Tagged]) -> str | None:
    """The 12-month duration period that ends latest among the revenue tags (the fiscal year reported)."""
    periods = {t.period for t in tags if t.name.split(":")[-1] in CONCEPTS["revenue"]
               and t.period and "/" in t.period and "Axis" not in t.context and "Member" not in t.context}
    years = [p for p in periods if 350 <= _days(p) <= 380]
    return max(years, key=lambda p: p.split("/")[1]) if years else None


def _printed(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        return None


def extract(db: Session, tenant: str, doc_id: str, entity: str, tags: list[Tagged]) -> dict:
    period = latest_fiscal_year(tags)
    if period is None:
        return {"period": None, "created": [], "rejected": [{"metric": "*", "reason": "no 12-month revenue tag"}]}
    label = f"FY{period.split('/')[1][:4]}"
    balance = f"@{period.split('/')[1]}"  # balance-sheet figures are instants at the fiscal year end
    created, rejected = [], []
    for metric, concepts in CONCEPTS.items():
        want = balance if metric in BALANCE else period
        cand = [t for t in tags if t.name.split(":")[-1] in concepts and t.period == want
                and "Axis" not in t.context and "Member" not in t.context and t.row]
        if not cand:
            rejected.append({"metric": metric, "reason": f"no {concepts[0]} tag for {label}"})
            continue
        t = cand[0]
        printed = _printed(t.text)
        if printed is None:
            rejected.append({"metric": metric, "reason": f"unreadable number {t.text!r}"})
            continue
        scale = Decimal(10) ** int(t.scale or 0)
        value = printed * scale * (-1 if t.negative else 1)
        try:
            f = add_verified_fact(db, tenant_id=tenant, entity=entity, metric=metric, period=label, value=value,
                                  unit="USD", document_id=doc_id, page=t.page, quote=t.row, scale=scale)
            created.append({"fact_id": f.id, "metric": metric, "period": label, "value": str(value),
                            "page": t.page, "quote": t.row})
        except CitationError as e:
            rejected.append({"metric": metric, "reason": str(e)})
    return {"period": label, "created": created, "rejected": rejected}
