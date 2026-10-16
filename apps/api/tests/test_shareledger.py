"""Numbers from the Monzo Bank SH01/SH02/SH19 filings in the golden set (s02, s03, s05), as stated."""
from decimal import Decimal as D

from fastapi.testclient import TestClient

from app.main import app
from app.shareledger import Event, reconcile
from tests.helpers import new_tenant


def test_same_day_forms_stated_against_the_same_base_are_combined_not_chained():
    led = reconcile(D(11234414), "SH01 2025-02-04", [
        Event("allot", "2025-03-12", "SH01 filed 2025-03-20", D(53819), D(11288233)),
        Event("allot", "2025-03-12", "SH01 filed 2025-03-21", D(15519568), D(26753982)),
    ])
    assert led.running == D(26807801) and not led.problems
    assert [e.status for e in led.entries[1:]] == ["same_base", "same_base"]


def test_consolidation_ratio_and_continuity_through_sh19_and_sh01():
    led = reconcile(D(192447561), "SH19 2024-03-13", [
        Event("statement", "2024-03-13", "SH19", total_after=D(192447561)),
        Event("allot", "2024-03-14", "SH01", D(152439), D(192600000)),
        Event("consolidate", "2024-03-14", "SH02", old_total=D(192600000), total_after=D(19260)),
    ])
    assert led.running == D(19260) and not led.problems
    assert led.entries[-1].detail == "10000-for-1"


def test_a_form_that_matches_nothing_is_reported_and_does_not_move_the_total():
    led = reconcile(D(1000), "open", [Event("allot", "2024-01-01", "SH01 x", D(10), D(1011))])
    assert led.running == D(1000) and led.entries[-1].status == "unreconciled"
    assert "1010" in led.problems[0]


def test_bad_consolidation_inputs():
    led = reconcile(D(100), "open", [Event("consolidate", "2024-01-01", "SH02", old_total=D(99), total_after=D(9))])
    assert led.problems and led.running == D(100)
    led = reconcile(D(100), "open", [Event("consolidate", "2024-01-01", "SH02", old_total=D(100), total_after=D(30))])
    assert "whole ratio" in led.problems[0]


def test_endpoint():
    c = TestClient(app)
    h = new_tenant(c, "sl1")
    r = c.post("/calc/share-ledger", headers=h, json={"opening": "11234414", "opening_source": "SH01 2025-02-04", "events": [
        {"kind": "allot", "date": "2025-03-12", "source": "A", "allotted": "53819", "total_after": "11288233"},
        {"kind": "allot", "date": "2025-03-12", "source": "B", "allotted": "15519568", "total_after": "26753982"}]})
    assert r.status_code == 200 and r.json()["running"] == "26807801"
    bad = c.post("/calc/share-ledger", headers=h, json={"opening": "1", "opening_source": "x", "events": [
        {"kind": "allot", "date": "not-a-date", "source": "A", "allotted": "1", "total_after": "2"}]})
    assert bad.status_code == 422
