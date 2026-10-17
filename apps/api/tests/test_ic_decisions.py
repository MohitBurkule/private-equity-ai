from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_decisions_append_in_order_and_outcome_is_checked():
    h = new_tenant(c, "ic1")
    body = {"deal": "Acme", "outcome": "hold", "rationale": "Need FY24 QoE first", "dissent": "Lower multiple",
            "dissenter": "VP"}
    assert c.post("/ic/decisions", headers=h, json={**body, "outcome": "maybe"}).status_code == 422
    first = c.post("/ic/decisions", headers=h, json=body).json()
    second = c.post("/ic/decisions", headers=h, json={**body, "outcome": "proceed", "dissent": None,
                                                     "dissenter": None}).json()
    rows = c.get("/ic/decisions", params={"deal": "Acme"}, headers=h).json()
    assert [r["id"] for r in rows] == [first["id"], second["id"]]
    assert rows[0]["dissent"] == "Lower multiple" and rows[1]["outcome"] == "proceed"
