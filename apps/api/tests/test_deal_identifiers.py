from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}


def tenant(name):
    t = c.post("/admin/tenants", json={"name": name}, headers=ADMIN).json()
    return {"Authorization": f"Bearer {t['api_key']}"}


def test_cik_and_lei_are_normalised_and_match_exactly():
    h = tenant("ids")
    body = {"name": "Acme Holdings", "stage": "ic", "cik": "0001234567",
            "lei": "529900t8bm49ayz5gb55"}
    r = c.post("/deals", headers=h, json=body).json()
    assert r["cik"] == "1234567" and r["lei"] == "529900T8BM49AYZ5GB55"
    assert c.get("/seen-before", params={"q": "1234567"}, headers=h).json()["hits"][0]["rule"] == "cik"
    assert c.get("/seen-before", params={"q": "529900T8BM49AYZ5GB55"}, headers=h).json()["hits"][0]["rule"] == "lei"


def test_aliases_are_matched_like_names_and_round_trip():
    h = tenant("aliases")
    r = c.post("/deals", headers=h, json={"name": "Project Atlas", "stage": "dd",
                                          "aliases": ["Atlas Software Ltd", "Atlas Software Ltd", "Atlas SaaS"]}).json()
    assert r["aliases"] == ["Atlas Software Ltd", "Atlas SaaS"]  # deduped, order kept
    hits = c.get("/seen-before", params={"q": "Atlas Software"}, headers=h).json()["hits"]
    assert [(x["name"], x["rule"]) for x in hits] == [("Project Atlas", "alias")]


def test_identifiers_are_validated_and_editable_with_write_rights():
    h = tenant("ids-validate")
    assert c.post("/deals", headers=h, json={"name": "Bad", "lei": "short"}).status_code == 422
    assert c.post("/deals", headers=h, json={"name": "Bad2", "cik": "12x"}).status_code == 422
    c.post("/deals", headers=h, json={"name": "Good", "stage": "ic"})
    r = c.patch("/deals/Good", headers=h, json={"aliases": ["Good Co"], "cik": "42"}).json()
    assert r["aliases"] == ["Good Co"] and r["cik"] == "42"
