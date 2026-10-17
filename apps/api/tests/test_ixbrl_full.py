from app.ixbrl_full import figures, period_of, read_filing

FILING = """<html><body>
<div style="page-break-after: always">Cover page text</div>
<div style="display:none"><ix:nonFraction name="us-gaap:Revenues" contextRef="Duration_1_1_2018_To_12_31_2018_x" scale="6">1</ix:nonFraction></div>
<div style="page-break-after: always"><table><tr><td>Net sales</td>
<td>$<ix:nonFraction name="us-gaap:Revenues" contextRef="Duration_1_1_2019_To_12_31_2019_abc" scale="6">32,136</ix:nonFraction></td>
<td><ix:nonFraction name="us-gaap:Revenues" contextRef="Duration_1_1_2019_To_12_31_2019_us-gaap_BusinessAcquisitionAxis_mmm_MM" scale="6">300</ix:nonFraction></td>
</tr></table></div>
</body></html>"""


def test_dates_read_month_first():
    assert period_of("Duration_1_1_2019_To_12_31_2019_abc") == ("2019-01-01", "2019-12-31")


def test_dimensional_context_has_no_period():
    assert period_of("Duration_1_1_2019_To_12_31_2019_us-gaap_BusinessAcquisitionAxis_mmm_MM") is None


def test_pages_split_on_breaks_and_hidden_figures_dropped():
    pages, tags = read_filing(FILING)
    assert [p.label for p in pages] == ["p. 1", "p. 2"]
    assert "Cover page text" in pages[0].text
    assert [t.text for t in tags] == ["32,136", "300"]


def test_figure_carries_its_table_row_and_page():
    _, tags = read_filing(FILING)
    (fig,) = figures(tags, "us-gaap:Revenues", "2019-01-01/2019-12-31")
    assert fig.page == 2
    assert fig.row == "Net sales $ 32,136 300"


def test_opaque_context_ids_take_period_from_definition():
    html = """<ix:resources>
<xbrli:context id="c-7"><xbrli:entity/><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="c-8"><xbrli:entity/><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="c-9"><xbrli:entity><xbrli:segment><xbrldi:explicitMember dimension="x">y</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
</ix:resources>
<div><table><tr><td>Total assets</td><td><ix:nonFraction name="us-gaap:Assets" contextRef="c-8" scale="6">22,311</ix:nonFraction></td></tr></table></div>
<div><table><tr><td>Revenues</td><td><ix:nonFraction name="us-gaap:Revenues" contextRef="c-7" scale="6">8,504</ix:nonFraction></td></tr></table></div>"""
    _, tags = read_filing(html)
    (assets,) = figures(tags, "us-gaap:Assets", "@2025-12-31")
    assert assets.row == "Total assets 22,311"
    assert [t.text for t in figures(tags, "us-gaap:Revenues", "2025-01-01/2025-12-31")] == ["8,504"]


def test_sign_minus_marks_a_loss():
    html = """<ix:resources>
<xbrli:context id="c-1"><xbrli:entity/><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
</ix:resources>
<table><tr><td>Net income (loss)</td><td>(<ix:nonFraction name="us-gaap:NetIncomeLoss" contextRef="c-1" scale="6" sign="-">747</ix:nonFraction>)</td></tr></table>"""
    _, tags = read_filing(html)
    (loss,) = figures(tags, "us-gaap:NetIncomeLoss", "2025-01-01/2025-12-31")
    assert loss.negative is True
    assert loss.text == "747"
    assert loss.row == "Net income (loss) ( 747 )"


def test_unsigned_figure_is_positive_and_scale_is_kept():
    html = """<ix:resources>
<xbrli:context id="c-2"><xbrli:entity/><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
</ix:resources>
<table><tr><td>Total assets</td><td><ix:nonFraction name="us-gaap:Assets" contextRef="c-2" scale="3">3,263,190</ix:nonFraction></td></tr></table>"""
    _, tags = read_filing(html)
    (assets,) = figures(tags, "us-gaap:Assets", "@2025-12-31")
    assert assets.negative is False
    assert assets.scale == 3
