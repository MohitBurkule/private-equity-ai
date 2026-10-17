import io
import json
import zipfile
from pathlib import Path

import pytest

from app import agent as ag
from app import newsfeed, opendata_tools, sanctions

FX = Path(__file__).parent / "fixtures" / "open"
F13 = FX / "f13"
EXPECTED = {"open_funding_rounds", "open_entity_lookup", "open_macro_series", "open_deal_leads", "open_news",
            "open_sanctions_screen", "open_13f_holdings", "open_adviser_search"}


def call(tool, /, **args):
    return ag.call_tool(ag.Ctx(db=None, who=None), tool, args)  # tools here never touch db/who


def test_all_tools_registered_read_only():
    assert EXPECTED <= set(ag.TOOLS) and not any(ag.TOOLS[n].writes for n in EXPECTED)


def test_macro_leads_and_entity_use_injected_fetch(monkeypatch):
    docs = {"fredgraph": (FX / "fred.csv").read_bytes(), "efts": (FX / "efts_merger.json").read_bytes(),
            "gleif": (FX / "gleif.json").read_bytes(), "wikidata": (FX / "wikidata_search.json").read_bytes()}
    monkeypatch.setattr(opendata_tools, "fetch", lambda u: next(v for k, v in docs.items() if k in u or k + "." in u))
    m = call("open_macro_series", series_id="DGS10")
    assert m["date"] == "2026-10-15" and m["value"] == "5.10" and m["source"].endswith("/series/DGS10")
    leads = call("open_deal_leads", since="2026-09-01", until="2026-10-15", limit=2)
    assert len(leads) == 2 and leads[0]["url"].startswith("https://www.sec.gov/")
    e = call("open_entity_lookup", name="Blackstone")
    assert e["gleif"][0]["lei"] == "5299004LW4QWGZUB8Y96" and e["wikidata"][0]["qid"] == "Q880942"


def test_rounds_decimal_to_text_and_quarter_check(monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in ("FORMDSUBMISSION", "OFFERING", "ISSUERS"):
            z.writestr(f"{n}.tsv", (FX.parent / "formd" / f"{n}.tsv").read_text())
    monkeypatch.setattr(opendata_tools, "fetch", lambda u: buf.getvalue())
    r = call("open_funding_rounds", issuer="rhino gp", year=2024, quarter=1)
    assert r[0]["offered"] == "12000000" and r[0]["url"].startswith("https://www.sec.gov/Archives/")
    json.dumps(r)
    with pytest.raises(ag.ToolError):
        call("open_funding_rounds", issuer="x", year=2024, quarter=5)


def test_news_sanctions_and_bad_args(monkeypatch):
    monkeypatch.setattr(newsfeed, "default_fetch", lambda u: (FX / "bbc_rss.xml").read_bytes())
    assert len(call("open_news", feed="bbc_business", limit=2)) == 2
    with pytest.raises(ag.ToolError):
        call("open_news", feed="nope")
    monkeypatch.setattr(sanctions, "default_fetch", lambda u: (FX / "sdn_sample.csv").read_bytes())
    s = call("open_sanctions_screen", name="Michael Kuajien")
    assert s["matches"][0]["how"] == "exact" and "screening aid" in s["note"]
    with pytest.raises(ag.ToolError):
        call("open_sanctions_screen", name="x", dataset="../etc")


def test_bulk_tools_need_env_path_then_work(monkeypatch, tmp_path):
    monkeypatch.delenv("PE_13F_ZIP", raising=False)
    with pytest.raises(ag.ToolError, match="PE_13F_ZIP"):
        call("open_13f_holdings", manager="blackstone")
    p = tmp_path / "q.zip"
    with zipfile.ZipFile(p, "w") as z:
        for n in ("SUBMISSION", "COVERPAGE", "INFOTABLE"):
            z.write(F13 / f"{n}.tsv", f"{n}.tsv")
    monkeypatch.setenv("PE_13F_ZIP", str(p))
    r = call("open_13f_holdings", manager="blackstone inc", limit=3)
    assert r["manager"]["name"] == "Blackstone Inc." and len(r["holdings"]) == 3
    assert call("open_13f_holdings", manager="zzzz") == []
    az = tmp_path / "adv.zip"
    with zipfile.ZipFile(az, "w") as z:
        z.write(FX / "adv_roster.csv", "roster.csv")
    monkeypatch.setenv("PE_ADV_ZIP", str(az))
    assert call("open_adviser_search", name="apollo")[0]["pe_funds"] == 214
