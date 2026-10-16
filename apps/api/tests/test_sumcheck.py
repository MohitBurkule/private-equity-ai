"""Figures from Netskope S-1/A (Sep 2025) and Alliance Laundry 424B4 (Oct 2025), as printed."""
from decimal import Decimal as D

from fastapi.testclient import TestClient

from app.main import app
from app.sumcheck import sum_check
from tests.helpers import new_tenant


def test_netskope_class_b_share_count_ties():
    r = sum_check([D(109316479), D(218897608), D(6059110)], D(334273197))
    assert r.status == "ties"


def test_alliance_further_adjusted_shares_have_a_600_share_gap():
    # 170,707,288 outstanding + 24,390,243 primary shares = 195,097,531; the prospectus states 195,096,931
    r = sum_check([D(170707288), D(24390243)], D(195096931))
    assert r.status == "gap" and r.difference == D(-600)


def test_rounding_is_labelled_not_passed():
    r = sum_check([D("10.4"), D("10.4")], D(21), rounding_unit=D("0.5"))
    assert r.status == "rounding"


def test_endpoint():
    c = TestClient(app)
    h = new_tenant(c, "sc1")
    r = c.post("/calc/sumcheck", headers=h, json={"parts": ["170707288", "24390243"], "stated": "195096931"})
    assert r.json()["status"] == "gap" and r.json()["difference"] == "-600"
