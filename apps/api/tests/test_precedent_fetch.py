from app.precedent_fetch import build, filing_text

INDEX = (
    b'{"hits":{"hits":[{"_id":"0001-26-000001:ex.htm","_source":{"ciks":["0000123456"],'
    b'"display_names":["Acme Corp"],"file_date":"2026-03-03","form":"8-K","items":["1.01"]}},'
    b'{"_id":"0002-26-000002:ex.htm","_source":{"ciks":["0000999999"],"display_names":["Beta Inc"],'
    b'"file_date":"2026-04-01","form":"8-K"}}]}}'
)
DOC_A = (
    b"<html><script>var x=1;</script><p>The enterprise value of approximately $1.2 billion. "
    b"The price represents 8.5x LTM revenue.</p><p>Other text.</p></html>"
)
DOC_B = b"<p>Filing has no price terms.</p>"


NO_HITS = b'{"hits":{"hits":[]}}'
PROXY = (
    b'{"hits":{"hits":[{"_id":"0003-26-000003:proxy.htm","_source":{"ciks":["0000999999"],'
    b'"display_names":["Acme Corp"],"file_date":"2026-05-01","form":"DEFM14A"}}]}}'
)
DOC_PROXY = b"<p>The merger values Acme at an enterprise value of approximately $1.5 billion.</p>"


def fake(url):
    if "efts" in url and "ciks=" in url:
        return PROXY if "DEFM14A" in url and "0000999999" in url else NO_HITS
    if "efts" in url:
        return INDEX
    if "proxy" in url:
        return DOC_PROXY
    if "0001" in url or "000123456" in url or "000000123456" in url:
        return DOC_A
    if "999999" in url or "0002" in url:
        return DOC_B
    raise OSError("unreachable")


def test_filing_text_strips_script_and_keeps_sentences():
    t = filing_text(DOC_A)
    assert "var x" not in t and "8.5x LTM revenue" in t


def test_build_cites_filing_url_and_skips_terms_free_filings():
    r = build("2026-01-01", "2026-12-31", fetch=fake)
    assert len(r["deals"]) == 2 and r["skipped"] == []  # Beta's 8-K has no terms, its proxy does
    deal = r["deals"][0]
    assert deal["terms"]["multiples"][0]["source_url"].startswith(
        "https://www.sec.gov/Archives/edgar/data/123456/"
    )
    assert deal["terms"]["ev_musd"]["value"] == "1200.0"
    assert (
        r["stats"]["revenue"]["n"] == 1
        and r["stats"]["revenue"]["range_shown"] is False
    )


def test_download_failure_is_recorded_not_raised():
    def flaky(url):
        if "efts" in url:
            return INDEX
        raise OSError("boom")

    r = build("2026-01-01", "2026-12-31", fetch=flaky)
    assert r["deals"] == [] and len(r["skipped"]) == 2
    assert all(s["reason"].startswith("download failed") for s in r["skipped"])


def test_ex99_exhibit_read_and_cited():
    index = b'{"directory":{"item":[{"name":"deal_8k.htm"},{"name":"ex99-1.htm"},{"name":"ex10-1.htm"}]}}'
    ex99 = b"<p>The transaction values the company at an enterprise value of approximately $2.0 billion.</p>"

    def f(url):
        if url.endswith("index.json"):
            return index
        if url.endswith("ex99-1.htm"):
            return ex99
        if url.endswith("deal_8k.htm"):
            return b"<p>Merger agreement signed.</p>"
        raise OSError("nope")

    r = build(
        "2026-01-01", "2026-12-31", fetch=lambda u: f(u) if "efts" not in u else INDEX
    )
    deal = next(d for d in r["deals"] if d["name"].startswith("Acme"))
    assert deal["terms"]["ev_musd"]["value"] == "2000.0"
    assert deal["terms"]["ev_musd"]["source_url"].endswith("ex99-1.htm")


def test_proxy_form_scanned_and_unknown_form_refused():
    seen = []

    def f(url):
        seen.append(url)
        if "efts" in url:
            return b'{"hits":{"hits":[]}}'
        raise OSError("nope")

    r = build("2026-01-01", "2026-12-31", fetch=f, form="DEFM14A")
    assert r["deals"] == [] and any("forms=DEFM14A" in u for u in seen)
    try:
        build("2026-01-01", "2026-12-31", fetch=f, form="10-K")
        raise AssertionError
    except ValueError:
        pass


SAAS_DOC = (
    b"<p>Acme Software entered an agreement and plan of merger with Thoma Bravo, a private equity firm. "
    b"The enterprise value of approximately $900 million. The price represents 6.0x LTM revenue.</p>"
)
MFG_DOC = (
    b"<p>Widget Mfg agreed to be acquired by Thoma Bravo, a private equity firm, for $400 million. "
    b"The price represents 5.0x LTM revenue.</p>"
)


def theme_fake(url):
    if "efts" in url:
        return INDEX
    if "999999" in url or "0002" in url:
        return MFG_DOC
    return SAAS_DOC


def test_theme_keeps_sponsor_software_deals_with_cited_sentences():
    r = build("2026-01-01", "2026-12-31", fetch=theme_fake, theme="vertical_saas_take_private")
    assert [d["name"].split(" (")[0] for d in r["deals"]] == ["Acme Corp"]
    th = r["deals"][0]["theme"]
    assert "Thoma Bravo" in th["buyer"]["sentence"] and "Software" in th["target"]["sentence"]
    assert th["buyer"]["source_url"].startswith("https://www.sec.gov/Archives/edgar/data/123456/")
    assert r["skipped"] == [{"name": "Beta Inc (2026-04-01)", "url": r["skipped"][0]["url"],
                             "reason": "theme not stated: vertical_saas_take_private"}]


def test_unknown_theme_refused():
    import pytest

    with pytest.raises(ValueError):
        build("2026-01-01", "2026-12-31", fetch=theme_fake, theme="nope")


def test_proxy_fallback_when_8k_states_no_value():
    r = build("2026-01-01", "2026-12-31", fetch=fake)
    beta = [d for d in r["deals"] if d["name"].startswith("Beta")]
    assert len(beta) == 1
    assert beta[0]["terms_from"].startswith("merger proxy")
    assert beta[0]["terms"]["ev_musd"]["source_url"].endswith("proxy.htm")
    assert not [d for d in r["deals"] if d["name"].startswith("Acme") and "terms_from" in d]


def test_blank_check_company_is_skipped_not_a_deal():
    spac = (b'{"hits":{"hits":[{"_id":"0004-26-000004:ex.htm","_source":{"ciks":["0000777777"],'
            b'"display_names":["Bleichroeder Acquisition Corp. II"],"file_date":"2026-08-27","form":"8-K"}}]}}')

    def f(url):
        return spac if "efts" in url and "ciks=" not in url else DOC_A
    r = build("2026-01-01", "2026-12-31", fetch=f)
    assert r["deals"] == []
    assert r["skipped"][0]["reason"].startswith("blank-check company")
