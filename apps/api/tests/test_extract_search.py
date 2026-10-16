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
