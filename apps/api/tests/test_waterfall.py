import random
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.waterfall import PrefClass, waterfall
from tests.helpers import new_tenant

A = PrefClass("A", D(250), D(10_000_000))  # 25% of 1,000 shares as converted, 1x non-participating


def test_non_participating_takes_preference_when_exit_is_low():
    r = waterfall(D(20_000_000), [A], D(750))
    assert r.payouts["A"] == D(10_000_000) and r.payouts["common"] == D(10_000_000) and r.converted == []


def test_non_participating_converts_when_exit_is_high():
    r = waterfall(D(60_000_000), [A], D(750))
    assert r.converted == ["A"] and r.payouts["A"] == D(15_000_000) and r.payouts["common"] == D(45_000_000)


def test_participating_uncapped_gets_preference_plus_share():
    p = PrefClass("A", D(250), D(10_000_000), participating=True)
    r = waterfall(D(50_000_000), [p], D(750))
    assert r.payouts["A"] == D(10_000_000) + D(40_000_000) / 4


def test_participating_cap_binds_then_conversion_beats_it():
    p = PrefClass("A", D(250), D(10_000_000), participating=True, cap_multiple=D(2))
    low = waterfall(D(50_000_000), [p], D(750))
    assert low.payouts["A"] == D(20_000_000) and low.converted == []  # 10M + 10M share hits the 2x cap
    high = waterfall(D(200_000_000), [p], D(750))
    assert high.converted == ["A"] and high.payouts["A"] == D(50_000_000)


def test_seniority_pays_senior_first_and_equal_rank_shares_pro_rata():
    s = PrefClass("Senior", D(100), D(8_000_000), rank=1)
    j1 = PrefClass("J1", D(100), D(6_000_000), rank=2)
    j2 = PrefClass("J2", D(100), D(2_000_000), rank=2)
    r = waterfall(D(12_000_000), [s, j1, j2], D(700))
    assert r.payouts["Senior"] == D(8_000_000)
    assert r.payouts["J1"] == D(3_000_000) and r.payouts["J2"] == D(1_000_000) and r.payouts["common"] == 0


def test_payouts_always_sum_to_the_exit_value():
    rnd = random.Random(7)
    for _ in range(150):
        cls = [PrefClass(f"C{i}", D(rnd.randint(1, 500)), D(rnd.randint(1, 20)) * D(1_000_000),
                         D(rnd.choice([1, 1, 2])), rnd.randint(1, 2), rnd.random() < 0.5,
                         rnd.choice([None, D(2), D(3)])) for i in range(rnd.randint(1, 3))]
        exit_v = D(rnd.randint(0, 200)) * D(1_000_000)
        r = waterfall(exit_v, cls, D(rnd.randint(1, 1000)))
        assert sum(r.payouts.values()) == exit_v and all(v >= 0 for v in r.payouts.values())
        assert r.status == "ok"


def test_bad_inputs_and_endpoint():
    with pytest.raises(ValueError):
        waterfall(D(-1), [A], D(1))
    with pytest.raises(ValueError):
        waterfall(D(1), [A, A], D(1))
    c = TestClient(app)
    h = new_tenant(c, "wf1")
    r = c.post("/calc/waterfall", headers=h, json={"exit_value": "60000000", "common_shares": "750",
              "classes": [{"name": "A", "shares": "250", "invested": "10000000"}]})
    assert r.status_code == 200 and r.json()["converted"] == ["A"] and r.json()["payouts"]["common"] == "45000000.00"
    assert c.post("/calc/waterfall", headers=h, json={"exit_value": "-1", "common_shares": "1", "classes": []}).status_code == 422
