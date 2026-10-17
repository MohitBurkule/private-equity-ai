"""Keyless Companies House pages. SYNTHETIC: fixtures in tests/fixtures/companies_house are made up and only
match the public page layout. No real company or person is named."""
from pathlib import Path

import pytest

from app import people_enrich as pe

FIX = Path(__file__).parent / "fixtures" / "companies_house"


def _fix(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_officers_page_keeps_active_and_drops_resigned():
    out = pe.parse_ch_officers_page(_fix("officers.html"), "12345678")
    assert [p["name"] for p in out] == ["SYNTHETIC, Alex"]
    assert out[0]["role"] == "Director"
    assert out[0]["quote"] == "SYNTHETIC, Alex, Director"
    assert out[0]["url"] == "https://find-and-update.company-information.service.gov.uk/company/12345678/officers"


def test_psc_page_keeps_individuals_and_drops_corporates():
    out = pe.parse_ch_psc_page(_fix("psc.html"), "12345678")
    assert [p["name"] for p in out] == ["Mr SYNTHETIC Casey"]
    assert out[0]["quote"] == "Mr SYNTHETIC Casey, notified 20 November 2023"
    assert out[0]["source"] == "Companies House PSC (page)"


def test_keyless_combines_both_pages_with_injected_fetch():
    pages = {"officers": _fix("officers.html"), "persons-with-significant-control": _fix("psc.html")}

    def fake(url: str) -> bytes:
        key = "officers" if url.endswith("/officers") else "persons-with-significant-control"
        return pages[key].encode()

    people = pe.companies_house_people_keyless("12345678", fake)
    assert [p["name"] for p in people] == ["SYNTHETIC, Alex", "Mr SYNTHETIC Casey"]


def test_keyless_page_fetch_refuses_other_hosts():
    with pytest.raises(ValueError):
        pe._page("http://find-and-update.company-information.service.gov.uk/company/1/officers")
    with pytest.raises(ValueError):
        pe._page("https://example.test/company/1/officers")


def test_companies_house_people_uses_keyless_when_no_key(monkeypatch):
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    monkeypatch.setattr(pe, "companies_house_people_keyless", lambda n: [{"name": "SYNTHETIC, Alex"}])
    assert pe.companies_house_people("12345678") == [{"name": "SYNTHETIC, Alex"}]
