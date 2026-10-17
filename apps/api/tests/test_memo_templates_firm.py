from fastapi.testclient import TestClient

from app.main import app
from tests.test_mnpi_docs import ADMIN
from tests.test_oidc import _sso, _token

c = TestClient(app)


def _tenant(name):
    t = c.post("/admin/tenants", json={"name": name}, headers=ADMIN).json()
    return t["tenant_id"], {"Authorization": f"Bearer {t['api_key']}"}


def test_firm_template_saves_lists_and_orders_sections(monkeypatch):
    _sso(monkeypatch)
    _, h = _tenant("firm-tpl")
    saved = c.post("/memo/templates", headers=h, json={"name": "firm-ic", "sections": ["risks", "financial"]})
    assert saved.status_code == 201 and saved.json()["sections"] == ["risks", "financial"]
    names = {t["name"]: t["built_in"] for t in c.get("/memo/templates", headers=h).json()["items"]}
    assert names == {"ic": True, "snapshot": True, "firm-ic": False}
    assert c.get("/memo/sections?entity=Acme&template=firm-ic", headers=h).status_code == 200


def test_bad_templates_are_refused(monkeypatch):
    _sso(monkeypatch)
    _tid, h = _tenant("firm-tpl-bad")
    assert c.post("/memo/templates", headers=h, json={"name": "ic", "sections": ["risks"]}).status_code == 422
    assert c.post("/memo/templates", headers=h, json={"name": "Bad Name", "sections": ["risks"]}).status_code == 422
    assert c.post("/memo/templates", headers=h, json={"name": "okay", "sections": ["secret"]}).status_code == 422
    assert c.post("/memo/templates", headers=h, json={"name": "okay", "sections": ["risks", "risks"]}).status_code == 422
    assert c.get("/memo/sections?entity=Acme&template=nope", headers=h).status_code == 422


def test_restricted_key_cannot_save_a_firm_template(monkeypatch):
    _sso(monkeypatch)
    tid, _ = _tenant("firm-tpl-scope")
    scoped = {"Authorization": f"Bearer {_token(tenant=tid, role='partner', sub='tess', deals=['Atlas'])}"}
    assert c.post("/memo/templates", headers=scoped, json={"name": "firm-x", "sections": ["risks"]}).status_code == 403


def test_firm_heading_text_and_intro_print_in_memo(monkeypatch):
    _sso(monkeypatch)
    _tid, h = _tenant("firm-tpl-text")
    body = {"name": "firm-text", "sections": ["risks", "financial"],
            "headings": {"risks": "Key risks (firm wording)"}, "intro": "Prepared for the Monday IC."}
    saved = c.post("/memo/templates", headers=h, json=body)
    assert saved.status_code == 201, saved.text
    assert saved.json()["headings"] == {"risks": "Key risks (firm wording)"}
    item = next(t for t in c.get("/memo/templates", headers=h).json()["items"] if t["name"] == "firm-text")
    assert item["intro"] == "Prepared for the Monday IC."
    # heading for a section the template does not carry, a markdown heading, or an over-long intro are refused
    assert c.post("/memo/templates", headers=h, json={**body, "name": "bad-a",
                                                     "headings": {"derived": "x"}}).status_code == 422
    assert c.post("/memo/templates", headers=h, json={**body, "name": "bad-b",
                                                     "headings": {"risks": "# Risks"}}).status_code == 422
    assert c.post("/memo/templates", headers=h, json={**body, "name": "bad-c",
                                                     "intro": "x" * 501}).status_code == 422
