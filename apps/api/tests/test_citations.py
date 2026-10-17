from decimal import Decimal

from app.citations import numbers_in, parse_number, quote_in_page, verify_number


def test_parentheses_negative():
    assert parse_number("(1,577)").value == Decimal(-1577)


def test_sign_flip_allowed_for_outflow():
    assert verify_number(Decimal(1577), "Purchases of PP&E (1,577) (1,488)", outflow=True)


def test_sign_flip_rejected_for_profit_shown_in_parentheses():
    # A printed loss must not be stored as a profit.
    assert not verify_number(Decimal(747), "Net income (loss) $ ( 747 ) $ ( 2,862 )")


def test_loss_asked_as_negative_with_loss_label():
    assert verify_number(Decimal(-747), "Net income (loss) 747 2,862")


def test_loss_asked_as_negative_without_loss_label_rejected():
    assert not verify_number(Decimal(-747), "Net income 747 2,862")


def test_printed_loss_matches_signed_claim():
    assert verify_number(Decimal(-747), "Net income (loss) $ ( 747 ) $ ( 2,862 )")


def test_wrong_number_rejected():
    assert not verify_number(Decimal(1578), "Purchases of PP&E (1,577)")


def test_scale_thousands():
    assert verify_number(Decimal(5466000), "Total current liabilities 5,466", Decimal(1000))


def test_quote_whitespace_insensitive():
    assert quote_in_page("total  current\nliabilities", "Total current liabilities 5,466")
    assert not quote_in_page("total assets", "Total current liabilities")


def test_numbers_in():
    assert [n.value for n in numbers_in("EPS 1.22 vs 1.54")] == [Decimal("1.22"), Decimal("1.54")]
