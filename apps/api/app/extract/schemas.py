"""Extraction schemas for PE diligence documents. A schema is a list of numeric fields; the model
proposes {value, page, quote} per field and code decides what is accepted (see extract/run.py)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    metric: str
    unit: str  # USD | pct | x | count | year
    description: str


SCHEMAS: dict[str, list[Field]] = {
    "debt": [
        Field("debt.principal", "USD", "Total principal amount or commitment of the facility"),
        Field("debt.margin_pct", "pct", "Interest margin over the base rate, in percent"),
        Field("debt.maturity_year", "year", "Final maturity year"),
        Field("debt.max_net_leverage_x", "x", "Maximum net leverage covenant, as a multiple"),
        Field("debt.min_interest_cover_x", "x", "Minimum interest cover covenant, as a multiple"),
    ],
    "customer_concentration": [
        Field("customers.top1_pct", "pct", "Largest customer as percent of revenue"),
        Field("customers.top5_pct", "pct", "Top five customers as percent of revenue"),
        Field("customers.top10_pct", "pct", "Top ten customers as percent of revenue"),
    ],
    "arr": [
        Field("arr.arr", "USD", "Annual recurring revenue"),
        Field("arr.nrr_pct", "pct", "Net revenue retention, percent"),
        Field("arr.gross_churn_pct", "pct", "Gross churn, percent"),
        Field("arr.customers", "count", "Number of customers"),
    ],
    "ebitda_bridge": [
        Field("ebitda.reported", "USD", "Reported EBITDA"),
        Field("ebitda.adjusted", "USD", "Adjusted EBITDA"),
        Field("ebitda.adjustments_total", "USD", "Total of management adjustments"),
    ],
}
