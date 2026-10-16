import io

from docx import Document as Docx
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant
from tests.test_covenants import setup

c = TestClient(app)


def build(h):
    co, fact = setup(h)
    thr = fact("debt.max_net_leverage_x", "cov", 0)
    o = fact("net_leverage_x", "Q2", 2)
    c.post(f"/portfolio/companies/{co}/observations", params={"fact_id": o}, headers=h)
    c.post(f"/portfolio/companies/{co}/covenants", json={"kpi_metric": "net_leverage_x", "operator": "<=",
                                                         "threshold_fact_id": thr}, headers=h)
    return co


def test_report_lists_breach_first_with_sources():
    h = new_tenant(c, "rp1")
    build(h)
    r = c.get("/portfolio/report", headers=h).json()
    assert r["breaches"][0]["company"] == "Co" and r["breaches"][0]["status"] == "breach"
    k = r["companies"][0]["kpis"][0]
    assert k["metric"] == "net_leverage_x" and k["sources"][0]["page"] == 1


def test_report_docx_and_isolation_and_wall():
    h = new_tenant(c, "rp2")
    build(h)
    res = c.get("/portfolio/report.docx", headers=h)
    assert res.status_code == 200
    text = "\n".join(p.text for p in Docx(io.BytesIO(res.content)).paragraphs)
    assert "BREACH" in text and "net_leverage_x Q2" in text
    other = new_tenant(c, "rp3")
    assert c.get("/portfolio/report", headers=other).json() == {"companies": [], "breaches": []}
