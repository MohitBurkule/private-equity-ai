"""Reference calls: turns by speaker; flags for MNPI and for commercial risk. Stores nothing."""
from fastapi.testclient import TestClient

from app.main import app
from app.reference_calls import review
from tests.helpers import new_tenant

c = TestClient(app)
CALL = """Interviewer: How is the platform working for you?
Customer: Honestly we are evaluating alternatives after the price increase.
Customer: The renewal is in March and we may switch to a competitor.
Interviewer: Anything about the deal we should know?
Customer: Our board approved a sale that is not yet announced.
"""


def test_commercial_and_mnpi_lines_are_flagged_with_their_kind():
    out = review(CALL)
    assert out["turns"] == 5
    assert out["speakers"] == ["Customer", "Interviewer"]
    kinds = {(f["line"], f["kind"]) for f in out["flags"]}
    assert (2, "commercial") in kinds and (3, "commercial") in kinds
    assert (5, "mnpi") in kinds


def test_plain_turns_are_not_flagged():
    assert review("Interviewer: Thanks for your time.\nCustomer: Happy to help.")["flags"] == []


def test_endpoint_stores_nothing_and_returns_the_review():
    h = new_tenant(c, "rc1")
    r = c.post("/dd/reference-calls/review", headers=h, json={"transcript": CALL})
    assert r.status_code == 200 and r.json()["turns"] == 5
    assert any(f["kind"] == "mnpi" for f in r.json()["flags"])
