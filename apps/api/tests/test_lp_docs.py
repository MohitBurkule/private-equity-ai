from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.lp_docs import (
    Cite,
    Flow,
    Kpi,
    capital_call_notice,
    lp_letter,
    notice_shares,
    to_docx,
    to_pptx,
)
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def cite(v, s):
    return Cite(v, s, f"https://example.test/{s}")


FLOWS = [Flow(date(2024, 1, 15), Decimal(-1000), cite("1000", "call1")),
         Flow(date(2025, 6, 1), Decimal(400), cite("400", "dist1"))]


def test_letter_metrics_and_every_figure_cited():
    m = lp_letter("Fund I", date(2026, 9, 30), FLOWS, cite("900", "nav"),
                  [Kpi("Acme", "ARR", "Q3 2026", cite("12.5m", "kpi1"))], tone=cite("formal", "tone1"))
    text = [t for p in m.paragraphs for t, _ in p]
    assert any("DPI 0.40x, RVPI 0.90x, TVPI 1.30x" in t for t in text)
    assert any(t.startswith("Net IRR:") for t in text)
    assert all(n is not None for p in m.paragraphs for t, n in p if any(ch.isdigit() for ch in t))  # no uncited number
    assert m.paragraphs[0][0][1] == 1  # tone rule is source 1


def test_letter_without_tone_says_so_and_refuses_empty_flows():
    m = lp_letter("Fund I", date(2026, 9, 30), FLOWS, cite("900", "nav"), [])
    assert "No accepted LP tone rule" in m.paragraphs[0][0][0]
    with pytest.raises(ValueError):
        lp_letter("Fund I", date(2026, 9, 30), [], cite("900", "nav"), [])


def test_notice_shares_pro_rata_and_add_up_exactly():
    s = notice_shares(Decimal(100), {"A": Decimal(1), "B": Decimal(1), "C": Decimal(1)})
    assert sum(s.values()) == Decimal(100) and s["A"] == Decimal("33.34")
    with pytest.raises(ValueError):
        notice_shares(Decimal(0), {"A": Decimal(1)})


def test_capital_call_one_lp_cites_commitment_and_notice_period():
    com = {"A": cite("2000000", "lpa-A"), "B": cite("3000000", "lpa-B")}
    m = capital_call_notice("Fund I", cite("500000", "call2"), "Acme follow-on", date(2026, 11, 1),
                            cite("10", "terms"), com, lp="A")
    last = m.paragraphs[-1]
    assert last[0][0].startswith("Your share: 200,000.00") and last[0][1] == m.sources.index(com["A"]) + 1
    with pytest.raises(ValueError):
        capital_call_notice("Fund I", cite("500000", "call2"), "x", date(2026, 11, 1), cite("10", "t"), com, lp="Z")


def test_renderers_produce_files():
    m = lp_letter("Fund I", date(2026, 9, 30), FLOWS, cite("900", "nav"), [])
    assert to_docx(m)[:2] == b"PK" and to_pptx(m)[:2] == b"PK"


def test_endpoints_return_json_docx_and_refuse_bad_format():
    h = new_tenant(c, "lp1")
    body = {"fund": "Fund I", "as_of": "2026-09-30",
            "flows": [{"on": "2024-01-15", "amount": "-1000", "source": {"value": "1000", "source": "call1"}}],
            "nav": {"value": "900", "source": "nav"}}
    j = c.post("/lp/letter", headers=h, json=body).json()
    assert j["sources"][0]["source"] == "call1"
    r = c.post("/lp/letter?format=docx", headers=h, json=body)
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert c.post("/lp/letter?format=xls", headers=h, json=body).status_code == 422
    call = {"fund": "Fund I", "amount": {"value": "500000", "source": "call2"}, "purpose": "Acme",
            "due": "2026-11-01", "notice_days": {"value": "10", "source": "terms"},
            "commitments": {"A": {"value": "2000000", "source": "lpa-A"}, "B": {"value": "3000000", "source": "lpa-B"}}}
    assert "sources" in c.post("/lp/capital-call", headers=h, json=call).json()
