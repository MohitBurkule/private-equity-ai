"""Playbook report: every rule gets an outcome against the document. A limit with no number is not_compared,
never clear. A firm playbook passed in replaces the default for that call."""
import copy

from app.legal import PLAYBOOK, extract, playbook_report, red_flags

CREDIT = [
    (1, "The Total Net Leverage Ratio shall not exceed 6.00 to 1.00 as of any quarter end."),
    (2, "The Maturity Date means June 30, 2031."),
]


def _by_rule(report):
    return {r["rule"]: r["status"] for r in report}


def test_fired_rule_is_flagged_and_unmatched_limit_is_not_compared_not_clear():
    report = _by_rule(playbook_report(extract(CREDIT, "credit")))
    assert report["leverage_loose"] == "flagged"
    assert all(s in {"flagged", "clear", "not_compared"} for s in report.values())


def test_limit_with_no_stated_number_is_not_compared():
    report = playbook_report(extract(CREDIT, "credit"))
    cover = [r for r in report if r["term"] == "min_interest_coverage"]
    assert cover and all(r["status"] == "not_compared" for r in cover)


def test_report_covers_every_rule_in_the_playbook():
    report = playbook_report(extract(CREDIT, "credit"))
    assert [r["rule"] for r in report] == [r["id"] for r in PLAYBOOK]


def test_a_firm_playbook_with_a_looser_limit_clears_the_same_document():
    firm = copy.deepcopy(PLAYBOOK)
    for rule in firm:
        if rule["id"] == "leverage_loose":
            rule["limit"] = 7.0
    result = extract(CREDIT, "credit")
    assert any(f["rule"] == "leverage_loose" for f in red_flags(result))
    assert not any(f["rule"] == "leverage_loose" for f in red_flags(result, firm))
    assert _by_rule(playbook_report(result, firm))["leverage_loose"] == "clear"


def test_playbook_report_endpoint_404s_on_a_document_outside_the_tenant():
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.helpers import new_tenant

    c = TestClient(app)
    h = new_tenant(c, "pbr1")
    assert c.get("/documents/no-such-doc/playbook-report?doc_type=credit", headers=h).status_code == 404
