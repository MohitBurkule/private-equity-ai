"""Live check of the keyless Companies House parser against real public pages. Opt-in: runs only when
CH_LIVE=1, so CI and the default suite never touch the network. Each company costs two requests, with a gap."""
import os
import re
import time

import pytest

from app import people_enrich as pe

MONZO = "09446231"  # corporate PSCs only, many officers
SINDLESHAM = "09720492"  # small company with an individual PSC
pytestmark = pytest.mark.skipif(os.environ.get("CH_LIVE") != "1", reason="set CH_LIVE=1 for the live CH check")


def _people(number: str) -> list[dict]:
    officers = pe._page(pe.CH_OFFICERS.format(n=number)).decode("utf-8", errors="replace")
    time.sleep(2)
    psc = pe._page(pe.CH_PSC.format(n=number)).decode("utf-8", errors="replace")
    time.sleep(2)
    return pe.parse_ch_officers_page(officers, number) + pe.parse_ch_psc_page(psc, number)


def test_live_monzo_officers_parse():
    people = [p for p in _people(MONZO) if p["source"].startswith("Companies House officers")]
    assert len(people) >= 5, "officer layout changed or no active officers parsed"
    assert all(re.match(r"^[^,]+, .+", p["name"]) for p in people), people


def test_live_individual_psc_parses():
    psc = [p for p in _people(SINDLESHAM) if p["source"].startswith("Companies House PSC")]
    assert psc, "no individual PSC parsed: the PSC layout has changed"
    for p in psc:
        assert p["quote"].startswith(p["name"]) and ", notified " in p["quote"]
        assert p["url"] == pe.CH_PSC.format(n=SINDLESHAM)
