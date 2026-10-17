"""Live check of the keyless Companies House parser against a real public page. Opt-in: runs only when
CH_LIVE=1, so CI and the default suite never touch the network. Makes two requests and sleeps between them."""
import os
import re
import time

import pytest

from app import people_enrich as pe

MONZO = "09446231"
pytestmark = pytest.mark.skipif(os.environ.get("CH_LIVE") != "1", reason="set CH_LIVE=1 for the live CH check")


def test_live_officers_and_psc_pages_parse():
    officers = pe._page(pe.CH_OFFICERS.format(n=MONZO)).decode("utf-8", errors="replace")
    time.sleep(2)
    psc = pe._page(pe.CH_PSC.format(n=MONZO)).decode("utf-8", errors="replace")
    people = pe.parse_ch_officers_page(officers, MONZO) + pe.parse_ch_psc_page(psc, MONZO)
    assert people, "no active people parsed: the page layout has changed"
    for p in people:
        assert re.match(r"^[^,]+, .+", p["name"]) or p["source"].startswith("Companies House PSC"), p
        assert p["quote"].startswith(p["name"]) and p["url"].startswith("https://find-and-update.company-information.service.gov.uk/")
