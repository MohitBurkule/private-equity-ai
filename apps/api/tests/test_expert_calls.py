from fastapi.testclient import TestClient

from app.expert_calls import flags, parse
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
CALL = """Analyst: How is demand for their product?
Expert: Demand is steady. Their board approved a plan
to expand capacity next year, which is not yet announced.
Analyst: Thanks.
"""


def test_turns_keep_wrapped_lines_and_flags_point_at_the_turn():
    turns = parse(CALL)
    assert [t.speaker for t in turns] == ["Analyst", "Expert", "Analyst"]
    assert "not yet announced" in turns[1].text
    fl = flags(turns)
    assert [(f.line, f.speaker, f.phrase) for f in fl] == [(2, "Expert", "not yet announced"),
                                                            (2, "Expert", "board approved")]


def test_review_endpoint_returns_flags_without_storing_anything():
    h = new_tenant(c, "expert1")
    out = c.post("/dd/expert-calls/review", headers=h, json={"transcript": CALL}).json()
    assert out["turns"] == 3 and out["speakers"] == ["Analyst", "Expert"]
    assert {f["phrase"] for f in out["flags"]} == {"not yet announced", "board approved"}
