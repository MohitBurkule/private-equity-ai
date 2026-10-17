from decimal import Decimal

from fastapi.testclient import TestClient

from app.flagship import lbo_inputs, lbo_step
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
TXT = b"<html><body><p>Mutual non-disclosure agreement. Governing law: Delaware. The term is two years from the effective date.</p></body></html>"


def steps_of(j):
    return {s["step"]: s for s in j["steps"]}


def test_lbo_inputs_must_be_cited_to_this_document_or_labelled():
    raw = {"ebitda": {"value": "10", "source": {"document_id": "d1", "page": 1, "quote": "x"}},
           "leverage": {"value": "5", "assumption": "sponsor view, not from the CIM"}}
    inputs, assumed = lbo_inputs(raw, "d1")
    assert assumed == ["leverage"] and inputs["ebitda"].value == Decimal(10)
    try:
        lbo_inputs({"ebitda": {"value": "10", "source": {"document_id": "other"}}}, "d1")
        raise AssertionError("expected refusal")
    except ValueError as e:
        assert "this document" in str(e)
    assert lbo_step({}, "d1").status == "skipped"


def test_run_reports_each_step_and_skips_what_it_cannot_do():
    h = new_tenant(c, "fs1")
    up = c.post("/documents", files={"file": ("nda.html", TXT, "text/html")}, headers=h)
    assert up.status_code in (200, 201), up.text
    doc = up.json()["id"]
    j = c.post("/flagship/run", headers=h, json={"document_id": doc, "entity": "Acme", "legal_doc_type": "nda"}).json()
    s = steps_of(j)
    assert s["intake"]["status"] == "ok" and s["extraction"]["status"] == "skipped"
    assert s["legal"]["status"] == "ok" and "red_flags" in s["legal"]["result"]
    assert s["lbo"]["status"] == "skipped" and s["memo"]["status"] == "skipped"  # no verified facts for Acme
    assert c.post("/flagship/run", headers=h, json={"document_id": "nope", "entity": "A"}).status_code == 404


def test_ebitda_is_operating_income_plus_da_from_verified_extraction():
    from app.flagship import Step, derive_ebitda
    ext = Step("extraction", "ok", result={"created": [
        {"metric": "operating_income", "value": "1000", "page": 3, "quote": "Operating income 1,000"},
        {"metric": "depreciation_amortization", "value": "250", "page": 4, "quote": "Depreciation 250"}]})
    spec = derive_ebitda([ext], "doc-1", "10k.htm")
    assert spec["value"] == "1250" and spec["source"]["document_id"] == "doc-1"
    assert spec["source"]["quote"] == "derived: Operating income 1,000 + Depreciation 250"
    assert derive_ebitda([Step("extraction", "ok", result={"created": []})], "doc-1", "10k.htm") is None


def test_crosscheck_flags_a_figure_that_differs_from_companyfacts():
    import json

    from app.flagship import Step, crosscheck_step
    ext = Step("extraction", "ok", result={"period_end": "2025-12-31", "created": [
        {"metric": "revenue", "value": "1000", "page": 1, "quote": "Revenue 1,000"},
        {"metric": "total_assets", "value": "500", "page": 2, "quote": "Total assets 500"}]})
    cf = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [{"start": "2025-01-01", "end": "2025-12-31", "val": 999, "form": "10-K"}]}},
        "Assets": {"units": {"USD": [{"end": "2025-12-31", "val": 500, "form": "10-K"}]}}}}}
    st = crosscheck_step(ext, "1166003", lambda url: json.dumps(cf).encode())
    assert st.status == "failed" and st.result["conflicts"][0]["companyfacts"] == "999"
    assert st.result["matched"][0]["metric"] == "total_assets"
    assert crosscheck_step(ext, None, None).status == "skipped"


def test_comps_band_widens_only_when_fewer_than_five_peers():
    from app.flagship import comps_step
    from app.peers import Peer
    calls = []

    def discover(revenue, sic, exclude, pages, low, high, want=10):
        calls.append((low, high, want))
        return [Peer(f"{len(calls)}{i:09d}", Decimal(1), "FY2025", "u", "r", f"P{i}") for i in range(2)]

    st = comps_step(Decimal(1000), "4213", set(), 1, discover)
    assert [(lo, hi) for lo, hi, _ in calls] == [(Decimal("0.5"), Decimal(2)), (Decimal("0.33"), Decimal(3))]
    assert calls[1][2] == 8 and len(st.result["peers"]) == 4

    calls.clear()
    def enough(revenue, sic, exclude, pages, low, high, want=10):
        calls.append((low, high))
        return [Peer(f"9{i:09d}", Decimal(1), "FY2025", "u", "r", f"Q{i}") for i in range(5)]
    comps_step(Decimal(1000), "4213", set(), 1, enough)
    assert calls == [(Decimal("0.5"), Decimal(2))]


def test_legal_model_reader_keeps_only_quoted_sentences_on_the_page():
    from app import legal, legal_reader

    class Local:
        def __init__(self, replies):
            self.replies = list(replies)

        def complete(self, system, prompt):
            return self.replies.pop(0)
    pages = [(1, "This Agreement is governed by the laws of the State of New York. A change of control needs consent.")]
    absent = ["governing_law", "change_of_control"]
    # 1: quote on the page and states the term -> kept. 2: quote not on the page -> dropped, not shown.
    llm = Local(['{"quote": "This Agreement is governed by the laws of the State of New York.", "page": 1}',
                 '{"quote": "A change of control is an event.", "page": 1}'])
    out = legal_reader.read(pages, "credit", absent, llm)
    assert [f["term"] for f in out["findings"]] == ["governing_law"]
    assert out["findings"][0]["value"] == "New York" and out["findings"][0]["page"] == 1
    assert out["dropped"] == [{"term": "change_of_control", "reason": "quote is not on the cited page"}]
    assert legal.TERMS["governing_law"]["doc"]


def test_flagship_reads_an_html_exhibit_stored_as_blocks():
    c = TestClient(app)
    h = new_tenant(c, "html-legal")
    html = b"<html><body><p>This Agreement is governed by the laws of the State of New York.</p></body></html>"
    up = c.post("/documents", files={"file": ("exhibit.htm", html, "text/html")}, headers=h).json()
    r = c.post("/flagship/run", headers=h, json={"document_id": up["id"], "entity": "X", "legal_doc_type": "credit"})
    steps = steps_of(r.json())
    assert steps["intake"]["result"]["pages"] >= 1
    assert steps["legal"]["status"] == "ok"
    assert "gov_law_absent" not in [f["rule"] for f in steps["legal"]["result"]["red_flags"]]


VERIFYME = ("This Amendment, and all claims or causes of action based upon, arising out of, or related to the Agreement "
            "or the transactions contemplated hereby, shall be governed by, and construed in accordance with, the Laws "
            "of the State of Delaware, without giving effect to principles or rules of conflict of laws. The statutory, "
            "fiduciary and other duties of the directors of the Company shall in each case be governed by the laws of "
            "the Cayman Islands.")


def test_governing_law_anchors_on_the_clause_and_returns_the_named_law():
    from app import legal
    out = legal.extract([(1, "Notices shall go to Austin, Texas. " + VERIFYME)], "spa")
    assert next(f["value"] for f in out["findings"] if f["term"] == "governing_law") == "Delaware"
    bare = legal.extract([(1, "The Company is organised in the Cayman Islands and its office is in Texas.")], "spa")
    assert "governing_law" in bare["absent"]


def test_reader_flags_a_rule_model_disagreement_for_review_without_picking():
    from app import legal, legal_reader

    class Local:
        def __init__(self, replies):
            self.replies = list(replies)

        def complete(self, system, prompt):
            return self.replies.pop(0)
    pages = [(1, VERIFYME)]
    rule = [{"term": "governing_law", "value": "Cayman Islands"}]
    out = legal_reader.read(pages, "spa", [], Local(
        [('{"quote": "This Amendment, and all claims or causes of action based upon, arising out of, or related to the '
         'Agreement or the transactions contemplated hereby, shall be governed by, and construed in accordance with, the '
         'Laws of the State of Delaware, without giving effect to principles or rules of conflict of laws.", "page": 1}')]), found=rule)
    assert out["findings"] == []
    assert out["review"][0]["status"] == "conflict"
    assert out["review"][0]["rule_value"] == "Cayman Islands" and out["review"][0]["model_value"] == "Delaware"
    assert legal.TERMS["governing_law"]["doc"]


def test_legal_model_reader_positive_case_from_a_real_merger_exhibit():
    """VerifyMe EX-2.1 (2026-08-12): governing law is written 'shall be governed by, and construed in accordance with,
    the Laws of the State of Delaware'. The reader keeps the real quote and rejects a quote the page does not contain."""
    from app import legal, legal_reader

    class Local:
        def __init__(self, replies):
            self.replies = list(replies)

        def complete(self, system, prompt):
            return self.replies.pop(0)
    sentence = ("This Amendment, and all claims or causes of action based upon, arising out of, or related to the Agreement "
                "or the transactions contemplated hereby, shall be governed by, and construed in accordance with, the Laws "
                "of the State of Delaware, without giving effect to principles or rules of conflict of laws.")
    pages = [(1, "5. Governing Law. " + sentence)]
    assert [f["value"] for f in legal.extract(pages, "spa")["findings"] if f["term"] == "governing_law"] == ["Delaware"]
    real = legal_reader.read(pages, "spa", ["governing_law"], Local(
        ['{"quote": "' + sentence + '", "page": 1}']))
    assert [f["term"] for f in real["findings"]] == ["governing_law"]
    assert real["findings"][0]["value"] == "Delaware"
    fake = legal_reader.read(pages, "spa", ["governing_law"], Local(
        ['{"quote": "This Agreement is governed by the laws of the State of New York.", "page": 1}']))
    assert fake["findings"] == [] and fake["dropped"][0]["reason"] == "quote is not on the cited page"


def test_legal_model_reader_reads_an_amount_first_termination_fee_from_a_real_merger_exhibit():
    """GBTG EX-2.3 (2025-09): '... pay ... a fee in the amount of $25,000,000 (the "Termination Fee")'. The rules did not
    read the amount before the term; the reader keeps the real quote, and a quote the page does not hold is rejected."""
    from app import legal_reader

    class Local:
        def __init__(self, replies):
            self.replies = list(replies)

        def complete(self, system, prompt):
            return self.replies.pop(0)
    sentence = ("Parent shall pay, or cause to be paid, to the Company a fee in the amount of $25,000,000 "
                "(the “Termination Fee”).")
    pages = [(23, "Section 7.2(b). " + sentence)]
    real = legal_reader.read(pages, "spa", ["termination_fee"], Local(['{"quote": "' + sentence + '", "page": 23}']))
    assert [(f["term"], f["value"]) for f in real["findings"]] == [("termination_fee", "$25,000,000")]
    fake = legal_reader.read(pages, "spa", ["termination_fee"], Local(
        ['{"quote": "Parent shall pay a fee in the amount of $30,000,000 (the “Termination Fee”).", "page": 23}']))
    assert fake["findings"] == [] and fake["dropped"][0]["reason"] == "quote is not on the cited page"


def test_comps_peer_with_a_market_ev_fact_gets_its_cited_multiple():
    from types import SimpleNamespace

    from app.flagship import comps_step
    from app.peers import Peer
    peers = [Peer("1", Decimal(100), "FY2025", "u1", "r", "RXO INC"), Peer("2", Decimal(50), "FY2025", "u2", "r", "NO EV")]

    calls = []

    def discover(*a, **k):
        calls.append(1)
        return peers if len(calls) == 1 else []

    evs = {"RXO INC": SimpleNamespace(id=7, value=Decimal(950), unit="USD")}
    st = comps_step(Decimal(1000), "4213", set(), 1, discover, ev_lookup=lambda n: evs.get(n))
    rxo, nov = st.result["peers"][:2]
    assert rxo["enterprise_value"] == "950" and rxo["ev_fact_id"] == 7 and rxo["ev_revenue_multiple"] == "9.50"
    assert "enterprise_value" not in nov


def test_peer_ev_in_another_unit_gets_no_multiple():
    from types import SimpleNamespace

    from app.flagship import _peer_row
    from app.peers import Peer
    p = Peer("1", Decimal(100), "FY2025", "u", "r", "EURCO")
    row = _peer_row(p, SimpleNamespace(id=3, value=Decimal(950), unit="EUR"))
    assert row["enterprise_value"] == "950" and row["ev_revenue_multiple"] is None and "not USD" in row["ev_note"]
