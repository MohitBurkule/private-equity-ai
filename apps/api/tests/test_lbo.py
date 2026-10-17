from decimal import Decimal

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.lbo import Cited, missing, run
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
SRC = {"document_id": "d1", "filename": "cim.pdf", "page": 4, "quote": "Adjusted EBITDA of $100.0 million"}
BASE = {"ebitda": "100", "entry_multiple": "10", "exit_multiple": "10", "leverage": "5", "interest_rate": "8",
        "tax_rate": "25", "cash_conversion": "60", "fees_pct": "2", "years": "5"}


def cited(d):
    return {k: Cited(Decimal(v), SRC) for k, v in d.items()}


def test_run_math_and_returns():
    r = run(cited(BASE))
    assert r.entry_ev == 1000 and r.debt == 500 and r.fees == 20 and r.equity == 520
    assert r.exit_ev == 1000 and r.exit_equity > 0 and r.moic > 1
    assert r.irr is not None and 0 < r.irr < 1
    assert len(r.schedule) == 5 and Decimal(r.schedule[-1]["debt_end"]) < 500


def test_refuses_missing_and_bad_inputs():
    d = dict(BASE)
    del d["tax_rate"]
    assert missing(cited(d)) == ["tax_rate"]
    try:
        run(cited(d))
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "tax_rate" in str(e)
    try:
        run(cited({**BASE, "leverage": "11"}))
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "equity must be positive" in str(e)


def test_endpoint_requires_citation_and_exports_xlsx():
    h = new_tenant(c, "lbo1")
    inputs = {k: {"value": v, "source": SRC} for k, v in BASE.items()}
    ok = c.post("/lbo/returns", headers=h, json={"inputs": inputs})
    assert ok.status_code == 200 and ok.json()["equity"] == "520"
    bad = {**inputs, "ebitda": {"value": "100"}}
    assert c.post("/lbo/returns", headers=h, json={"inputs": bad}).status_code == 422
    short = {k: v for k, v in inputs.items() if k != "years"}
    assert c.post("/lbo/returns", headers=h, json={"inputs": short}).status_code == 422
    x = c.post("/lbo/returns?xlsx=true", headers=h, json={"inputs": inputs})
    assert x.status_code == 200
    import io
    wb = load_workbook(io.BytesIO(x.content))
    rows = list(wb["Inputs"].iter_rows(values_only=True))
    assert rows[1][0] == "ebitda" and rows[1][2] == "cim.pdf" and rows[1][3] == 4 and "Adjusted EBITDA" in rows[1][4]
