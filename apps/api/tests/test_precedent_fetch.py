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


def fake(url):
    if "efts" in url:
        return INDEX
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
    assert len(r["deals"]) == 1
    deal = r["deals"][0]
    assert deal["terms"]["multiples"][0]["source_url"].startswith(
        "https://www.sec.gov/Archives/edgar/data/123456/"
    )
    assert deal["terms"]["ev_musd"]["value"] == "1200.0"
    assert r["skipped"][0]["reason"] == "no stated EV or multiple"
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
