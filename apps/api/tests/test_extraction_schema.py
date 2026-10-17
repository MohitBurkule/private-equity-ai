from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.extraction_schema import (
    CapTableRow,
    ConcentrationTable,
    Covenant,
    CustomerShare,
    DebtTranche,
)


def test_cap_table_rejects_negative_shares_and_pct_over_100():
    assert CapTableRow(holder="Fund I", share_class="A", shares=Decimal(1000), ownership_pct=Decimal("45.5"))
    with pytest.raises(ValidationError):
        CapTableRow(holder="Fund I", share_class="A", shares=Decimal(-1))
    with pytest.raises(ValidationError):
        CapTableRow(holder="Fund I", share_class="A", shares=Decimal(1), ownership_pct=Decimal(101))


def test_debt_tranche_needs_known_instrument_and_non_negative_principal():
    assert DebtTranche(lender="Bank", instrument="term_loan", principal=Decimal(500), maturity=date(2030, 1, 1))
    with pytest.raises(ValidationError):
        DebtTranche(lender="Bank", instrument="mezz", principal=Decimal(1))
    with pytest.raises(ValidationError):
        DebtTranche(lender="Bank", instrument="notes", principal=Decimal(-5))


def test_covenant_threshold_must_be_positive_and_operator_known():
    assert Covenant(name="Leverage", metric="net_leverage", operator="<=", threshold=Decimal("4.5"))
    with pytest.raises(ValidationError):
        Covenant(name="Leverage", metric="net_leverage", operator="<=", threshold=Decimal(0))
    with pytest.raises(ValidationError):
        Covenant(name="Leverage", metric="net_leverage", operator="==", threshold=Decimal(2))


def test_concentration_rejects_period_totals_over_100():
    ok = ConcentrationTable(rows=[CustomerShare(customer="A", period="FY24", revenue_pct=Decimal(40)),
                                  CustomerShare(customer="B", period="FY24", revenue_pct=Decimal(30))])
    assert len(ok.rows) == 2
    with pytest.raises(ValidationError):
        ConcentrationTable(rows=[CustomerShare(customer="A", period="FY24", revenue_pct=Decimal(70)),
                                 CustomerShare(customer="B", period="FY24", revenue_pct=Decimal(40))])
