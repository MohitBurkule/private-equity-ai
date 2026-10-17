from app.qoe import _STANDARD_COMPONENT, _row_label


def test_standard_ebitda_components_are_not_one_off_candidates():
    for quote in ("Sheet!B2: 20 | row: Interest expense", "Sheet!B3: 30 | row: Income tax provision",
                  "Sheet!B4: 40 | row: Depreciation and amortization", "Sheet!B5: 50 | row: D&A"):
        assert _STANDARD_COMPONENT.search(_row_label(quote)), quote
    assert not _STANDARD_COMPONENT.search(_row_label("Sheet!B6: 25 | row: Restructuring charges"))
