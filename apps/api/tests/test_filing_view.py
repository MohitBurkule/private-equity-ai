from app.filing_view import filing_page_html
from app.ixbrl_full import read_filing

FILING = """<html><head><style>.n{font-weight:bold}</style></head><body>
<ix:header><ix:resources>
<xbrli:context id="c-1"><xbrli:entity/><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
</ix:resources></ix:header>
<div><table><tr><td>Cover</td></tr></table></div>
<div style="page-break-after: always"></div>
<div><table><tr><td>Net income (loss)</td><td>(<ix:nonFraction name="us-gaap:NetIncomeLoss" contextRef="c-1" scale="6" sign="-">747</ix:nonFraction>)</td></tr></table></div>
<div style="page-break-after: always"></div>
<div><script>alert(1)</script><p>Next page text</p></div>
</body></html>"""


def test_page_is_bounded_by_breaks_and_keeps_filer_styles():
    _, tags = read_filing(FILING)
    doc, highlighted = filing_page_html(FILING, tags, 2, "Net income (loss) ( 747 )")
    assert highlighted is True
    assert ".n{font-weight:bold}" in doc
    assert "Net income (loss)" in doc
    assert "Cover" not in doc and "Next page text" not in doc


def test_figure_is_wrapped_as_the_highlight():
    _, tags = read_filing(FILING)
    doc, _ = filing_page_html(FILING, tags, 2, "Net income (loss) ( 747 )")
    assert '<ix:nonFraction class="pe-hl" name="us-gaap:NetIncomeLoss"' in doc


def test_scripts_are_removed_from_the_page():
    _, tags = read_filing(FILING)
    doc, _ = filing_page_html(FILING, tags, 2, "Net income (loss) ( 747 )")
    assert "<script" not in doc and "alert(1)" not in doc


def test_quote_not_matching_still_shows_page_unhighlighted():
    _, tags = read_filing(FILING)
    doc, highlighted = filing_page_html(FILING, tags, 2, "Total assets 44,659")
    assert highlighted is False
    assert 'class="pe-hl"' not in doc


def test_page_without_tagged_figure_returns_none():
    _, tags = read_filing(FILING)
    assert filing_page_html(FILING, tags, 1, "Cover") is None


def test_anchor_highlights_the_named_element():
    html = FILING.replace('<td>Net income (loss)</td>', '<td id="ni">Net income (loss)</td>')
    _, tags = read_filing(html)
    doc, highlighted = filing_page_html(html, tags, 2, "", anchor="ni")
    assert highlighted is True
    assert '<td class="pe-hl" id="ni">Net income (loss)</td>' in doc


def test_offset_highlights_the_figure_at_that_character():
    _, tags = read_filing(FILING)
    offset = FILING.index("<ix:nonFraction")
    doc, highlighted = filing_page_html(FILING, tags, 2, "", offset=offset)
    assert highlighted is True
    assert '<ix:nonFraction class="pe-hl"' in doc


def test_unknown_anchor_has_no_target():
    _, tags = read_filing(FILING)
    assert filing_page_html(FILING, tags, 2, "", anchor="missing") is None
