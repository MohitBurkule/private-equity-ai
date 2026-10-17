import os
from pathlib import Path

import pytest

from app.ch_match import load_candidates, match, normalise

CH_CSV = os.environ.get("CH_BASIC_CSV")


def test_normalise_drops_suffixes_and_punctuation():
    assert normalise("The Monzo Bank Limited.") == "MONZO BANK"
    assert normalise("Focus FS Ltd") == "FOCUS FS"


def test_exact_and_normalised_links_fuzzy_goes_to_review(tmp_path):
    ch = tmp_path / "ch.csv"
    ch.write_text(
        "CompanyName,CompanyNumber,CompanyStatus\n"
        "MONZO BANK LIMITED,09446231,Active\n"
        "ACME WIDGETS LTD,01111111,Active\n"
        "ACME WIDGETS LTD,02222222,Dissolved\n"
        "ACME WIDGET LTD,03333333,Active\n",
        encoding="utf-8",
    )
    cands = load_candidates(ch, ["Monzo Bank Limited", "Acme Widgets Ltd", "Acme Widgetz"])
    assert match("Monzo Bank Limited", cands).tier == "exact"
    m = match("Acme Widgets Ltd", cands)
    # two exact-name rows, one dissolved: the single live row links at normalised tier
    assert m.tier == "normalised" and m.company_number == "01111111" and not m.needs_review
    fz = match("Acme Widgetz", cands)
    # fuzzy: company_number is a suggestion only; needs_review means a human must confirm before linking
    assert fz.tier == "fuzzy" and fz.company_number == "03333333" and fz.needs_review


@pytest.mark.skipif(not CH_CSV, reason="needs CH file")
def test_real_file_monzo_exact():
    cands = load_candidates(Path(CH_CSV), ["Monzo Bank Limited"])
    m = match("Monzo Bank Limited", cands)
    assert m.company_number == "09446231" and not m.needs_review


def test_attach_sh01_only_to_auto_linked(tmp_path):
    from app.ch_match import Match, attach_sh01

    linked = Match("Monzo Bank Limited", "09446231", "MONZO BANK LIMITED", "exact", 1.0, False)
    s = attach_sh01(linked, "MzQ3OTUxNTIyOGFkaXF6a2N4")
    assert s and s.source_url.endswith("/company/09446231/filing-history/MzQ3OTUxNTIyOGFkaXF6a2N4/document?format=pdf")
    review = Match("Focus FS Limited", "15824328", "FOCUS FSR LTD", "fuzzy", 0.94, True)
    assert attach_sh01(review, "MzQ3OTUxNTIyOGFkaXF6a2N4") is None
