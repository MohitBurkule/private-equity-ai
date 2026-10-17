"""Portfolio LP report: each line is a cited figure from the company routes, and the report renders through the
same LP output paths as the letter."""
from tests.helpers import new_tenant
from tests.test_accounting_flow import _sync, c


def test_report_lists_cited_actuals_and_budget_against_actual(monkeypatch):
    h = new_tenant(c, "portfolio-lp-report")
    assert _sync(h, monkeypatch).status_code == 200
    co = next(x["company_id"] for x in c.get("/portfolio/submissions", params={"period": "2026-08"},
                                              headers=h).json()["submitted"])
    rev = next(k for k in c.get(f"/portfolio/companies/{co}/kpis", headers=h).json()
               if k["period"] == "2026-08" and k["metric"] == "revenue_usd")
    assert c.post(f"/portfolio/companies/{co}/observations?fact_id={rev['fact_id']}&kind=budget", headers=h).status_code == 201

    body = c.get("/portfolio/lp-report", params={"period": "2026-08", "prior": "2026-07"}, headers=h).json()
    texts = [p["text"] for para in body["paragraphs"] for p in para]
    assert "ACME:" in texts
    assert any(t.startswith("revenue_usd") and "2026-08" in t for t in texts)
    assert any("against budget" in t for t in texts)
    sources = [s["source"] for s in body["sources"]]
    assert "ACME-monthly.xlsx" in sources  # every line is cited to the document it was read from


def test_report_renders_docx_and_pptx(monkeypatch):
    h = new_tenant(c, "portfolio-lp-report-files")
    assert _sync(h, monkeypatch).status_code == 200
    for fmt, kind in (("docx", "wordprocessingml"), ("pptx", "presentationml")):
        r = c.get("/portfolio/lp-report", params={"period": "2026-08", "prior": "2026-07", "format": fmt}, headers=h)
        assert r.status_code == 200 and kind in r.headers["content-type"]
