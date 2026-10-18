"""Each language-model call is logged with model, sizes and latency; the report sums them per model. SYNTHETIC text."""
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import Base, make_engine
from app.llm import CappedLLM
from app.llm_report import summarise
from app.main import app
from app.models import LlmCall
from tests.helpers import new_tenant


class FakeLLM:
    id = "fake:model-a"

    def complete(self, system, prompt):
        return "synthetic answer"


def test_each_call_is_logged_with_sizes_and_model():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    llm = CappedLLM(FakeLLM(), db, "tenant-x")
    llm.complete("sys", "question?")
    row = db.query(LlmCall).one()
    assert row.model == "fake:model-a" and row.chars_in == len("sys") + len("question?")
    assert row.chars_out == len("synthetic answer") and row.latency_ms >= 0


def test_summary_counts_and_means_per_model():
    rows = [("m1", 10, 5, 100), ("m1", 20, 5, 300), ("m2", 1, 1, 50)]
    out = summarise(rows)
    assert out[0] == {"model": "m1", "calls": 2, "chars_in": 30, "chars_out": 10,
                      "latency_ms_mean": 200, "latency_ms_max": 300}
    assert out[1]["model"] == "m2" and out[1]["calls"] == 1


def test_report_route_is_tenant_scoped():
    h = new_tenant(TestClient(app), "llm-report")
    r = TestClient(app).get("/llm/report", params={"days": 3}, headers=h)
    assert r.status_code == 200 and r.json()["days"] == 3 and r.json()["models"] == []
