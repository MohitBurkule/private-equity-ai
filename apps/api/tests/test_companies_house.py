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


def test_numbers_import_keeps_active_skips_dissolved_and_unknown():
    from app.companies_house import CompanyRecord, company_numbers_to_targets

    records = {
        "01234567": CompanyRecord("01234567", "ACME LTD", "Active", None, None, ["62012 - Software"], "web"),
        "07654321": CompanyRecord("07654321", "OLD LTD", "Dissolved", None, None, [], "web"),
    }
    items, skipped = company_numbers_to_targets(["01234567", "07654321", "99999999"], fetch=records.get)
    assert [i.name for i in items] == ["ACME LTD"]
    assert items[0].source == "companies_house" and items[0].source_ref == "01234567"
    assert items[0].source_url.endswith("/company/01234567")
    assert skipped == ["07654321", "99999999"]


def test_unknown_status_is_skipped_not_assumed_active():
    from app.companies_house import CompanyRecord, company_numbers_to_targets

    no_status = CompanyRecord("02222222", "UNSURE LTD", None, None, None, [], "web")
    items, skipped = company_numbers_to_targets(["02222222"], fetch=lambda n: no_status)
    assert items == [] and skipped == ["02222222"]
