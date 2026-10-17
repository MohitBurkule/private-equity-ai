from pathlib import Path

from app.companies_house import parse_company_api, parse_company_page

FIXTURE = Path(__file__).parent / "fixtures" / "ch_web_company_page.html"


def test_keyless_page_parses_status_type_incorporation_and_sic():
    rec = parse_company_page(FIXTURE.read_text(encoding="utf-8"), "15296432")
    assert rec.name == "BRAMAND LTD"
    assert rec.status == "Dissolved"
    assert rec.company_type == "Private limited Company"
    assert rec.incorporated == "20 November 2023"
    assert rec.sic == ["99999 - Dormant Company"]
    assert rec.source == "web"


def test_missing_elements_stay_none_not_guessed():
    rec = parse_company_page("<html><body>nothing here</body></html>", "00000001")
    assert rec.name is None and rec.status is None and rec.sic == []


def test_api_body_maps_to_same_record_shape():
    rec = parse_company_api({"company_name": "ACME LTD", "company_status": "active", "type": "ltd",
                             "date_of_creation": "2010-01-02", "sic_codes": ["62012"]}, "01234567")
    assert rec.name == "ACME LTD" and rec.sic == ["62012"] and rec.source == "api"
