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
    (fig,) = figures(tags, "us-gaap:Revenues", "2019-01-01", "2019-12-31")
    assert fig.page == 2
    assert fig.row == "Net sales $ 32,136 300"
