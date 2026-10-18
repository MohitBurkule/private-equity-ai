import io
from decimal import Decimal

from openpyxl import Workbook

from app.bridge_workbook import bridge_lines
from app.citations import xlsx_location


def _book(rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Bridge"
    ws.append(["Item", "Kind", "Amount", "Period"])
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_each_line_is_cited_to_its_amount_cell():
    out = bridge_lines(_book([["Reported EBITDA", "reported", 120, "FY2025"],
                              ["Interest income", "deduction", 5, "FY2025"]]))
    assert [(x["cell"], x["kind"], x["amount"]) for x in out["lines"]] == [
        ("C2", "reported", Decimal(120)), ("C3", "deduction", Decimal(5))]
    sheet, cell, label = xlsx_location(out["lines"][1]["quote"])
    assert (sheet, cell, label) == ("Bridge", "C3", "Interest income")


def test_unknown_kind_and_text_amount_are_skipped_not_guessed():
    out = bridge_lines(_book([["Owner fee", "addback", 3, "FY2025"], ["Rent", "add_back", "n/a", "FY2025"],
                              ["Legal", "add_back", 7, "FY2025"]]))
    assert [x["item"] for x in out["lines"]] == ["Legal"]
    assert len(out["skipped"]) == 2


def test_missing_period_is_skipped():
    out = bridge_lines(_book([["Legal", "add_back", 7, None]]))
    assert out["lines"] == [] and out["skipped"][0]["reason"] == "no period"


def test_stored_lines_are_candidates_not_verified_facts(tmp_path):
    from sqlalchemy.orm import Session

    from app.bridge_workbook import store_candidates
    from app.db import Base, make_engine
    from app.models import Fact
    from app.qoe import normalized_ebitda

    path = tmp_path / "bridge.xlsx"
    path.write_bytes(_book([["Reported EBITDA", "reported", 120, "FY2025"],
                            ["Legal", "add_back", 7, "FY2025"]]))
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        out = store_candidates(s, "t", "Acme", path, "bridge.xlsx")
        facts = s.query(Fact).all()
        assert len(out["fact_ids"]) == 2 and {f.status for f in facts} == {"auto"}
        assert {f.metric for f in facts} == {"ebitda_bridge reported", "ebitda_bridge add_back"}
        assert all(f.sources[0].kind == "xlsx" and f.sources[0].anchor for f in facts)
        assert normalized_ebitda(s, "t", "Acme", "FY2025").missing  # unreviewed lines withhold the total
