from fastapi.testclient import TestClient

from app.main import app
from app.memo_diff import diff_memos
from tests.helpers import new_tenant

c = TestClient(app)


def test_changed_figure_shows_as_one_removed_and_one_added_line():
    prev = "# Acme\n\n- Revenue 100 [src 1]\n- Margin 20% [src 2]\n"
    cur = "# Acme\n\n- Revenue 120 [src 1]\n- Margin 20% [src 2]\n"
    d = diff_memos(prev, cur)
    assert d == {"unchanged": 3, "added": ["- Revenue 120 [src 1]"], "removed": ["- Revenue 100 [src 1]"],
                 "changed": True}


def test_identical_text_is_unchanged():
    d = diff_memos("# A\n- x\n", "# A\n- x\n")
    assert d["changed"] is False and d["added"] == [] and d["removed"] == []


def test_memo_diff_route_compares_against_sent_text():
    h = new_tenant(c, "memodiff")
    r = c.post("/memo/diff", headers=h, json={"entity": "Acme", "previous": "# Acme\n- old line\n"})
    assert r.status_code == 200
    body = r.json()
    assert body["entity"] == "Acme" and body["changed"] is True
    assert "- old line" in body["removed"]


def test_memo_diff_needs_previous_text():
    h = new_tenant(c, "memodiff2")
    assert c.post("/memo/diff", headers=h, json={"entity": "Acme", "previous": ""}).status_code == 422
