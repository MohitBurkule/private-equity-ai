import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.chfeed import accounts_filings, normalise_number
from app.main import app
from tests.helpers import new_tenant

# SYNTHETIC fixture (see its _note): shape only, not a real company.
DOC = (Path(__file__).parent / "fixtures" / "ch_filing_history_SYNTHETIC.json").read_bytes()


def test_only_accounts_and_missing_link_is_empty_not_invented():
    seen = []
    out = accounts_filings("1234", lambda u: seen.append(u) or DOC)
    assert "/company/00001234/filing-history?category=accounts" in seen[0]
    assert [f.period_end for f in out] == ["2024-03-31", "2023-03-31"]
    assert out[0].document_metadata_url.endswith("/document/AbCdEf123")
    assert out[1].document_metadata_url == ""


@pytest.mark.parametrize("n,ok", [("1234", "00001234"), ("sc123456", "SC123456"), ("12-34", None), ("123456789", None)])
def test_company_number_normalisation(n, ok):
    if ok is None:
        with pytest.raises(ValueError):
            normalise_number(n)
    else:
        assert normalise_number(n) == ok


def test_endpoint_503_without_key_and_404_for_unknown(monkeypatch):
    import app.main as m
    from app.chfeed import CompanyNotFound
    c = TestClient(app)
    h = new_tenant(c, "ch1")
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    assert c.get("/uk/company/00001234/accounts", headers=h).status_code == 503
    assert c.get("/uk/company/bad-id/accounts", headers=h).status_code == 422

    def missing(url):
        raise CompanyNotFound(url)
    m.app.dependency_overrides[m.get_ch_fetch] = lambda: missing
    try:
        assert c.get("/uk/company/00001234/accounts", headers=h).status_code == 404
        m.app.dependency_overrides[m.get_ch_fetch] = lambda: (lambda u: DOC)
        assert len(c.get("/uk/company/1234/accounts", headers=h).json()) == 2
    finally:
        m.app.dependency_overrides.clear()
    json.loads(DOC)
