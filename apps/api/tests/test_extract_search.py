from decimal import Decimal

from app.extract.tables import detect_scale, extract_rows
from app.search import PageIndex

PAGE = """Consolidated Statement of Cash Flows
(Millions)
Purchases of property, plant and equipment (PP&E) (1,577) (1,488) (1,373)
Net income 4,570 5,363 4,858
Narrative sentence with no numbers
"""


def test_scale_detected():
    assert detect_scale("(In thousands, except per share)") == Decimal(1000)
    assert detect_scale("nothing") == Decimal(1)


def test_rows_keep_raw_sign_and_order():
    rows = {r.label: r for r in extract_rows(PAGE.replace("(Millions)", "in millions"), 60)}
    capex = rows["Purchases of property, plant and equipment (PP&E)"]
    assert capex.raw_values == ("(1,577)", "(1,488)", "(1,373)")
    assert capex.values[0] == Decimal(-1577)
    assert capex.scale == Decimal(10) ** 6 and capex.page == 60
    assert "Narrative sentence with no numbers" not in rows


def test_search_scoped_and_ranked():
    idx = PageIndex([
        ("a", 1, "legal proceedings lawsuit filed"),
        ("a", 2, "purchases of property plant and equipment 1,577"),
        ("b", 1, "purchases of property plant and equipment 9,999"),
    ])
    hits = idx.search("capex", k=3, doc_ids={"a"})
    assert [(h.doc_id, h.page) for h in hits] == [("a", 2)]


def test_dollar_signs_and_spacing_stripped_from_raw():
    line = "Net income attributable to Pfizer Inc.      $         21,979      $       9,159"
    (row,) = extract_rows(line, 57)
    assert row.raw_values == ("21,979", "9,159")


def test_statement_page_ranks_up_for_financial_question_only():
    from app.search import PageIndex
    prose = "Our customers are important. " * 4
    table = "Consolidated Statements of Income. Revenues 100 Cost 60 Net income 40"
    idx = PageIndex([("d", 1, prose), ("d", 2, table + " customers")])
    assert idx.search("what is net income revenue for FY2022", k=1)[0].page == 2
    # Non-financial question: no boost, so the prose page with more query hits still wins.
    assert idx.search("who are the customers", k=1)[0].page == 1
