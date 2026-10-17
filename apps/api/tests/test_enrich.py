from fastapi.testclient import TestClient

from app import enrich
from app import main as m
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
PAGE = b"""<html><head><title> Acme   Widgets &amp; Co </title>
<meta name="description" content="Makers of industrial widgets.">
<meta property="og:site_name" content="Acme"></head><body><p>hi</p></body></html>"""


def test_parse_homepage_keeps_only_present_tags():
    f = enrich.parse_homepage(PAGE.decode())
    assert f == {"title": "Acme Widgets & Co", "description": "Makers of industrial widgets.", "site_name": "Acme"}
    assert enrich.parse_homepage("<html><body>no head</body></html>") == {"title": "", "description": "", "site_name": ""}


def test_check_url_refuses_non_public_and_plaintext_hosts():
    for bad in ["http://acme.test", "https://127.0.0.1/", "https://localhost/", "https://[::1]/",
                "https://user:pw@acme.test/", "https://intranet/"]:
        try:
            enrich.check_url(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    assert enrich.check_url("https://acme.test/about") == "https://acme.test/about"


def test_enrich_endpoint_stores_fields_with_their_url(monkeypatch):
    seen = []
    monkeypatch.setattr(m, "CONNECTOR_HTTP", lambda url, headers: (seen.append(url), PAGE)[1])
    h = new_tenant(c, "enrich")
    assert c.post("/targets", json=[{"name": "Acme", "source_ref": "acme-1", "source": "manual"}],
                  headers=h).status_code == 201
    target_id = c.get("/targets", headers=h).json()["items"][0]["id"]
    r = c.post(f"/targets/{target_id}/enrich/website", json={"url": "https://acme.test/"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert seen == ["https://acme.test/"]
    assert body["website"] == "https://acme.test/" and body["web_title"] == "Acme Widgets & Co"
    assert body["web_checked_at"] and body["fetched"]["site_name"] == "Acme"
    assert c.post(f"/targets/{target_id}/enrich/website", json={"url": "http://acme.test/"},
                  headers=h).status_code == 422
    assert c.post("/targets/999999/enrich/website", json={"url": "https://acme.test/"},
                  headers=h).status_code == 404
