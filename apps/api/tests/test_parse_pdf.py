from decimal import Decimal
from pathlib import Path

import pytest

from app.citations import quote_in_page, verify_number
from app.parse.pdf import extract_pages

SAMPLE = Path("/mnt/project-files/data/sec/3M_2018_10K.pdf")


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample data not present")
def test_3m_capex_on_cited_page():
    pages = extract_pages(SAMPLE)
    assert pages[0].number == 1
    # FinanceBench gold page index 59 is 0-based -> PDF page 60
    p = pages[60 - 1]
    assert quote_in_page("Purchases of property, plant and equipment", p.text)
    assert verify_number(Decimal(1577), p.text, outflow=True)
