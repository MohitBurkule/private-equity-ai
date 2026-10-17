"""End to end on the 3M FY2019 10-K: a fresh tenant, the filing uploaded, one flagship call.
Needs the filing and network access to SEC EDGAR, so it runs only when FLAGSHIP_3M=1 and SEC_USER_AGENT is set."""
import os
from pathlib import Path

import pytest
from app.main import app
from fastapi.testclient import TestClient

from tests.helpers import new_tenant

FILING = Path("/mnt/attach/project-files/data/edgar/3M_2019_10K.htm")
pytestmark = pytest.mark.skipif(not (os.environ.get("FLAGSHIP_3M") and os.environ.get("SEC_USER_AGENT")
                                     and FILING.exists()), reason="needs FLAGSHIP_3M=1, SEC_USER_AGENT and the filing")


def test_3m_flagship_end_to_end():
    c = TestClient(app)
    h = new_tenant(c, "3m")
    up = c.post("/documents", files={"file": ("3M_2019_10K.htm", FILING.read_bytes(), "text/html")}, headers=h)
    assert up.status_code in (200, 201), up.text
    body = {"document_id": up.json()["id"], "entity": "3M", "extract": True, "sic": "3841", "cik": "66740",
            "peers_pages": 10, "precedents": {"since": "2025-10-01", "until": "2026-10-16", "limit": 3},
            "lbo": {"inputs": {
                "entry_multiple": {"value": "12", "assumption": "illustrative entry multiple of EBITDA"},
                "exit_multiple": {"value": "12", "assumption": "exit at entry multiple"},
                "leverage": {"value": "5", "assumption": "illustrative leverage, x EBITDA"},
                "interest_rate": {"value": "0.08", "assumption": "illustrative cost of debt"},
                "tax_rate": {"value": "0.21", "assumption": "US federal statutory rate"},
                "cash_conversion": {"value": "0.7", "assumption": "illustrative FCF / EBITDA"},
                "fees_pct": {"value": "0.02", "assumption": "illustrative deal fees"},
                "years": {"value": "5", "assumption": "holding period"}}}}
    r = c.post("/flagship/run", headers=h, json=body)
    assert r.status_code == 200, r.text
    steps = {s["step"]: s for s in r.json()["steps"]}
    assert steps["extraction"]["status"] == "ok", steps["extraction"]
    created = {f["metric"]: f for f in steps["extraction"]["result"]["created"]}
    assert "revenue" in created and created["revenue"]["value"] == "32136000000"
    assert steps["memo"]["status"] == "ok"
    assert steps["lbo"]["status"] == "ok", steps["lbo"]
    assert steps["lbo"]["result"]["inputs"]["ebitda"]["source"]["quote"].startswith("derived:")
    assert steps["legal"]["status"] == "skipped"  # no 3M credit agreement in the data folder
    assert steps["comps"]["status"] == "ok" and steps["precedents"]["status"] == "ok"
    pptx = c.get("/memo.pptx?entity=3M", headers=h)
    assert pptx.status_code == 200 and pptx.content[:2] == b"PK"
