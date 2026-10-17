"""Workbook quotes must start with their cell. Both the colon form and the comma form locate a row."""
import pytest

from app.citations import xlsx_location


@pytest.mark.parametrize("quote", ["P&L!C14: 1,000 | row: Revenue", "P&L!C14, row: Revenue"])
def test_both_cell_first_forms_locate_the_row(quote):
    assert xlsx_location(quote) == ("P&L", "C14", "Revenue")


def test_cell_without_row_label_and_plain_text_refused():
    assert xlsx_location("P&L!C14: 1,000") == ("P&L", "C14", None)
    assert xlsx_location("Revenue 1,000 in FY24") is None
    assert xlsx_location("Revenue, row: x") is None
