from decimal import Decimal

from app.ixbrl import read_ixbrl


def doc(fixed="1,000", nca="500", talcl="1,500", na="1,500", eq="1,500", dim=False):
    ctx_dim = "<xbrldi:explicitMember dimension='x'>y</xbrldi:explicitMember>" if dim else ""
    return f"""<html><body>
<xbrli:context id="c1"><xbrli:period><xbrli:instant>2025-10-31</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="c0"><xbrli:period><xbrli:instant>2024-10-31</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="cd"><xbrli:entity><xbrli:segment>{ctx_dim or "<xbrldi:explicitMember/>"}</xbrli:segment></xbrli:entity>
<xbrli:period><xbrli:instant>2026-01-01</xbrli:instant></xbrli:period></xbrli:context>
<ix:nonFraction name="ns5:FixedAssets" contextRef="c1" scale="0">{fixed}</ix:nonFraction>
<ix:nonFraction name="ns5:NetCurrentAssetsLiabilities" contextRef="c1" scale="0">{nca}</ix:nonFraction>
<ix:nonFraction name="ns5:TotalAssetsLessCurrentLiabilities" contextRef="c1" scale="0">{talcl}</ix:nonFraction>
<ix:nonFraction name="ns5:NetAssetsLiabilities" contextRef="c1" scale="0">{na}</ix:nonFraction>
<ix:nonFraction name="ns5:Equity" contextRef="c1" scale="0">{eq}</ix:nonFraction>
<ix:nonFraction name="ns5:FixedAssets" contextRef="c0" scale="0">9,999</ix:nonFraction>
<ix:nonFraction name="ns5:FixedAssets" contextRef="cd" scale="0">7,777</ix:nonFraction>
</body></html>"""


def test_consistent_filing_is_reliable_and_uses_latest_nondimensional_instant():
    r = read_ixbrl(doc())
    assert r.instant == "2025-10-31" and r.facts["FixedAssets"] == Decimal(1000)
    assert r.reliable and r.checks == {"fixed+netcurrent=TALCL": True, "netassets=equity": True}


def test_broken_identity_marks_filing_unreliable():
    r = read_ixbrl(doc(talcl="1,600"))
    assert r.checks["fixed+netcurrent=TALCL"] is False and not r.reliable
    assert read_ixbrl(doc(eq="1,499")).reliable is False


def test_zerodash_scale_and_sign():
    html = doc().replace(">1,000<", ' format="ixt2:zerodash">-<')
    r = read_ixbrl(html.replace('scale="0">500', 'scale="3" sign="-">0.5'))
    assert r.facts["FixedAssets"] == 0
    assert r.facts["NetCurrentAssetsLiabilities"] == Decimal(-500)


def test_no_balance_sheet_means_cannot_check_not_reliable_claim():
    r = read_ixbrl("<html><body>nothing</body></html>")
    assert r.checks == {"fixed+netcurrent=TALCL": None, "netassets=equity": None}


def test_upload_ixbrl_flags_unreliable_filing_in_page_text():
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.helpers import new_tenant
    c = TestClient(app)
    h = new_tenant(c, "uk-t")
    good = c.post("/documents", files={"file": ("ok.html", doc().encode(), "text/html")}, headers=h).json()
    bad = c.post("/documents", files={"file": ("bad.html", doc(talcl="1,600").encode(), "text/html")},
                 headers=h).json()
    g = c.get(f"/documents/{good['id']}/pages/1", headers=h).json()["text"]
    b = c.get(f"/documents/{bad['id']}/pages/1", headers=h).json()["text"]
    assert "UNRELIABLE" not in g and "FixedAssets: 1,000" in g
    assert b.startswith("[UNRELIABLE") and "fixed+netcurrent=TALCL" in b


PNL_DOC = """<html><body>
<xbrli:context id="y25"><xbrli:period><xbrli:startDate>2024-11-01</xbrli:startDate><xbrli:endDate>2025-10-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="y24"><xbrli:period><xbrli:startDate>2023-11-01</xbrli:startDate><xbrli:endDate>2024-10-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="short"><xbrli:period><xbrli:startDate>2025-08-01</xbrli:startDate><xbrli:endDate>2025-10-31</xbrli:endDate></xbrli:period></xbrli:context>
<ix:nonFraction name="core:Turnover" contextRef="y25" scale="3">1,200</ix:nonFraction>
<ix:nonFraction name="core:GrossProfitLoss" contextRef="y25" scale="3">400</ix:nonFraction>
<ix:nonFraction name="core:OperatingProfit" contextRef="y25" scale="3">-50</ix:nonFraction>
<ix:nonFraction name="core:Turnover" contextRef="y24" scale="3">900</ix:nonFraction>
<ix:nonFraction name="core:Turnover" contextRef="short" scale="3">250</ix:nonFraction>
</body></html>"""


def test_pnl_read_for_latest_twelve_month_period_only():
    r = read_ixbrl(PNL_DOC)
    assert r.pnl == {"Turnover": Decimal(1200000), "GrossProfit": Decimal(400000), "OperatingProfit": Decimal(-50000)}
    assert r.pnl_period == "2024-11-01 to 2025-10-31"


def test_no_tagged_pnl_leaves_pnl_empty_and_does_not_touch_reliability():
    r = read_ixbrl(doc())
    assert r.pnl == {} and r.pnl_period is None and r.reliable
