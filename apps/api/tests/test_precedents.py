from decimal import Decimal

from app.precedents import extract, summarise

P1 = (
    "On March 3, 2026 Acme Corp entered into a merger agreement. The enterprise value of approximately "
    "$1.2 billion was agreed. The price represents 8.5x LTM revenue and 14x adjusted EBITDA."
)
P2 = (
    "The aggregate consideration was $850 million in cash. Nothing else is stated here."
)
ACQ = [(1, P1), (2, P2)]


def test_ev_and_multiples_cited_to_page():
    t = extract(ACQ)
    assert t["ev_musd"]["value"] == "1200.0" and t["ev_musd"]["page"] == 1
    assert t["ev_musd"]["needs_review"] is False
    by = {m["metric"]: m for m in t["multiples"]}
    assert by["revenue"]["value"] == "8.5" and by["revenue"]["page"] == 1
    assert by["ebitda"]["value"] == "14" and "adjusted EBITDA" in by["ebitda"]["quote"]
    assert t["absent"] == []


def test_missing_terms_listed_not_guessed():
    t = extract([(1, "The parties agreed to combine operations.")])
    assert t["ev_musd"] is None and t["multiples"] == []
    assert t["absent"] == ["enterprise_value", "multiple"]


def test_summary_needs_three_deals_and_cites_each_input():
    deals = []
    for i, x in enumerate(["6", "8", "10"]):
        deals.append(
            {
                "name": f"Deal {i}",
                "document_id": f"d{i}",
                "terms": extract([(1, f"The price represents {x}x LTM revenue.")]),
            }
        )
    s = summarise(deals)["revenue"]
    assert s["n"] == 3 and s["range_shown"] and Decimal(s["median"]) == Decimal(8)
    assert all(src["document_id"] and src["page"] == 1 for src in s["inputs"])
    small = summarise(deals[:2])["revenue"]
    assert small["range_shown"] is False


def test_zero_multiple_and_repeat_ignored():
    deals = [
        {
            "name": "X",
            "document_id": "x",
            "terms": extract([(1, "0x revenue. 5x revenue. 7x revenue.")]),
        }
    ]
    s = summarise(deals)["revenue"]
    assert s["n"] == 1 and s["inputs"][0]["value"] == "5"
    assert Decimal(s["median"]) == Decimal(5)


def test_banker_and_pro_forma_figures_flagged_and_left_out_of_stats():
    pages = [
        (
            1,
            "Piper Sandler calculated an implied transaction value of approximately $249.2 million.",
        ),
        (
            2,
            "The combined company has an enterprise value of approximately $5.0 billion.",
        ),
        (3, "The price represents 9x LTM revenue."),
    ]
    t = extract(pages)
    assert t["ev_musd"]["needs_review"] is True
    assert t["multiples"][0]["needs_review"] is False
    s = summarise([{"name": "A", "document_id": "a", "terms": t}])
    assert s == {} or "revenue" in s
