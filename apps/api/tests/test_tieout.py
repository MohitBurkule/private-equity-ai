"""Rows from the Alliance Laundry 424B4 (Oct 2025) Adjusted EBITDA bridge, 8 columns
(6M2025, 6M2024, FY2024..FY2019), as printed. Dropped-cell cases are simulated by removing one blank."""
from decimal import Decimal as D

from app.extract.tieout import tie_out

N = None
EBITDA = [193383, 189894, 345619, 316556, 261407, 239820, 215902, 251167]
ADJ = [219106, 196108, 383248, 328477, 271761, 258505, 220984, 251130]
FULL = {
    "refinancing": [1054, N, 33217, N, 223, N, N, N][:7] + [N],
    "sbc": [1771, 1776, 3263, 3343, 3144, 4230, 1668, 1941],
    "pension": [N, N, N, 7011, 4619, N, N, N],
    "strategic": [3044, 4668, 5803, 1083, 437, N, N, N],
    "fx": [19854, -230, -4654, 484, 1931, 6364, 3414, -1978],
    "union": [N, N, N, N, N, 2819, N, N],
    "earnouts": [N, N, N, N, N, 5272, N, N],
}


def dec(v):
    return [None if x is None else D(x) for x in v]


def run(rows):
    return tie_out({k: dec(v) for k, v in rows.items()}, [D(x) for x in EBITDA], [D(x) for x in ADJ])


def test_full_rows_tie():
    r = run(FULL)
    assert r.status == "resolved" and r.rows["fx"][1] == D(-230)


def test_row_with_a_dropped_blank_is_resolved_by_the_column_sums():
    short = dict(FULL)
    short["refinancing"] = [1054, N, 33217, N, 223, N, N]  # 7 tokens for 8 columns, as in the source text
    r = run(short)
    assert r.status == "resolved"
    assert r.rows["refinancing"] == [D(1054), 0, D(33217), 0, D(223), 0, 0, 0]


def test_wrong_total_has_no_solution():
    bad = dict(FULL)
    bad["sbc"] = [1771, 1776, 3263, 3343, 3144, 4230, 1668, 9999]
    assert run(bad).status == "no_solution"


def test_values_that_could_sit_in_two_columns_are_ambiguous_not_guessed():
    r = tie_out({"x": [D(5)]}, [D(0), D(0)], [D(5), D(5)])
    assert r.status == "no_solution"  # a single 5 cannot make both columns 5
    r = tie_out({"x": [D(5)]}, [D(0), D(0)], [D(0), D(0)])
    assert r.status == "no_solution"
    r = tie_out({"x": [D(5), D(5)]}, [D(0), D(0), D(0)], [D(5), D(5), D(0)])
    assert r.status == "resolved"
    r = tie_out({"x": [D(5)]}, [D(0), D(5)], [D(5), D(5)])
    assert r.status == "resolved" and r.rows["x"] == [D(5), D(0)]
    r = tie_out({"a": [D(5)], "b": [D(5)]}, [D(0), D(0)], [D(5), D(5)])
    assert r.status == "ambiguous" and r.solutions == 2


def test_too_many_placements_is_reported():
    rows = {f"r{i}": [D(1)] * 4 for i in range(8)}
    assert tie_out(rows, [D(0)] * 12, [D(1)] * 12).status == "too_large"


def test_endpoint():
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.helpers import new_tenant
    c = TestClient(app)
    h = new_tenant(c, "tie1")
    r = c.post("/calc/tieout", headers=h, json={"rows": {"a": ["5"]}, "base": ["0", "5"], "total": ["5", "5"]})
    assert r.status_code == 200 and r.json()["status"] == "resolved" and r.json()["rows"]["a"] == ["5", "0"]
