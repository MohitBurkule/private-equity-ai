import io

from fastapi.testclient import TestClient

from app import ch_search as cs
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
PAGE = """<ul><li class="type-company"><h3><a class="govuk-link" href="/company/15296432"
title="View company">
BRAMAND LTD
</a></h3>
<p class="meta crumbtrail inset">Matching previous names: <br/><span>MONZO</span></p>
<p class="meta crumbtrail"> 15296432 - Dissolved on 8 October 2024 </p>
<p>Llwyn Helyg, Llangybi, Pwllheli, Wales, LL53 6TB</p>
</li><li class="type-officer"><h3><a href="/officers/x">A PERSON</a></h3></li></ul>"""


def test_parse_html_keeps_companies_only_and_links_each_one():
    out = cs.parse_html(PAGE)
    assert len(out) == 1
    assert out[0].name == "BRAMAND LTD" and out[0].number == "15296432" and out[0].status == "Dissolved"
    assert out[0].company_url.endswith("/company/15296432")
    assert out[0].address.startswith("Llwyn Helyg")


def test_parse_api_shape():
    out = cs.parse_api({"items": [{"kind": "searchresults#company", "title": "X LTD", "company_number": "01234567",
                                   "company_status": "active", "address_snippet": "1 Road"}]})
    assert out[0].number == "01234567" and out[0].status == "active"


def test_search_uses_injected_fetch_and_endpoint_flags_imported(monkeypatch):
    monkeypatch.delenv("CH_API_KEY", raising=False)
    seen = []
    assert [x.number for x in cs.search("monzo", fetch=lambda u: (seen.append(u), PAGE)[1])] == ["15296432"]
    assert "search/companies?q=monzo" in seen[0]
    h = new_tenant(c, "chs1")
    c.post("/targets", headers=h, json=[{"name": "Known", "source_ref": "x", "sector": "Software"}])
    monkeypatch.setattr(cs, "search", lambda q, limit=20: cs.parse_html(PAGE))
    r = c.post("/targets/search/companies-house", headers=h, json={"query": "monzo"}).json()
    assert r["items"][0]["already_imported"] is False and r["items"][0]["number"] == "15296432"
    assert c.post("/targets/search/companies-house", headers=h, json={"query": " "}).status_code == 422


def test_requests_are_spaced(monkeypatch):
    sleeps = []
    monkeypatch.setattr(cs.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(cs.urllib.request, "urlopen", lambda req, timeout=30: io.BytesIO(b"<html/>"))
    cs._last[0] = cs.time.monotonic()
    cs._get("https://example.test/a")
    assert sleeps and sleeps[0] > 0
