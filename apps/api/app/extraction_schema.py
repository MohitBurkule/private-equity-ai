"""Typed shapes for structured facts that statements alone cannot carry: cap table, debt schedule and
covenants, customer concentration, and contract terms.

Why pydantic here: each row is extracted from a cited quote, so the validators are the cheap first gate.
They reject rows that cannot be true (negative shares, a percentage over 100, a covenant with no
threshold) before they reach the citation gate or the review queue. Nothing here stores anything; the
extractor produces these, and a row only becomes a Fact after it passes the citation check.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class CapTableRow(BaseModel):
    holder: str = Field(min_length=1)
    share_class: str = Field(min_length=1)
    shares: Decimal = Field(ge=0)
    ownership_pct: Decimal | None = Field(default=None, ge=0, le=100)


class DebtTranche(BaseModel):
    lender: str = Field(min_length=1)
    instrument: Literal["term_loan", "revolver", "notes", "other"]
    principal: Decimal = Field(ge=0)
    rate_pct: Decimal | None = Field(default=None, ge=0, le=100)
    maturity: date | None = None


class Covenant(BaseModel):
    name: str = Field(min_length=1)
    metric: Literal["net_leverage", "interest_cover", "fixed_charge_cover", "other"]
    operator: Literal["<=", ">="]
    threshold: Decimal
    test_date: date | None = None

    @field_validator("threshold")
    @classmethod
    def _positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("covenant threshold must be positive")
        return v


class CustomerShare(BaseModel):
    customer: str = Field(min_length=1)
    period: str = Field(min_length=1)
    revenue_pct: Decimal = Field(ge=0, le=100)


class ConcentrationTable(BaseModel):
    rows: list[CustomerShare]
    top_n_total_pct: Decimal | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _sums_fit(self) -> ConcentrationTable:
        # Customers in one period cannot add to more than 100% of revenue, even with rounding slack.
        by_period: dict[str, Decimal] = {}
        for r in self.rows:
            by_period[r.period] = by_period.get(r.period, Decimal(0)) + r.revenue_pct
        if any(total > Decimal("100.5") for total in by_period.values()):
            raise ValueError("customer shares in one period exceed 100% of revenue")
        return self


class ContractTerms(BaseModel):
    counterparty: str = Field(min_length=1)
    change_of_control: bool | None = None
    exclusivity: bool | None = None
    mfn: bool | None = None
    termination_notice_days: int | None = Field(default=None, ge=0, le=3650)
