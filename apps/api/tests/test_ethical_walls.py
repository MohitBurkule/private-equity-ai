import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.acl import (
    deal_hidden,
    deal_scope,
    format_wall,
    hidden_deal_names,
    mnpi_name_conflict,
    parse_wall,
    visible_doc_ids,
    visible_mnpi_deal_names,
)
from app.auth import principal_for_key
from app.main import SessionLocal, app
from app.models import Deal
from app.rls import bind_tenant
from tests.helpers import new_tenant_id

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}


def upload(h, deal, name):
    wb = Workbook()
    wb.active["A1"] = name
    b = io.BytesIO()
    wb.save(b)
    r = c.post("/documents", files={"file": (f"{name}.xlsx", b.getvalue(), "x")}, data={"deal": deal}, headers=h)
    assert r.status_code in (200, 201), r.text


def key(tid, **body):
    r = c.post(f"/admin/tenants/{tid}/keys", json=body, headers=ADMIN)
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['api_key']}"}


def setup(name):
    """Two deals with one document each, and a person on each side of a wall on Atlas."""
    creator, tid = new_tenant_id(c, name)
    assert c.post("/deals", headers=creator, json={"name": "Atlas"}).status_code == 201
    assert c.post("/deals", headers=creator, json={"name": "Beta"}).status_code == 201
    upload(creator, "Atlas", f"{name} atlas")
    upload(creator, "Beta", f"{name} beta")
    walled = key(tid, role="associate", identity="alice@fund.example")
    group_member = key(tid, role="associate", identity="dan@fund.example", groups=["deal-team"])
    scoped = key(tid, role="associate", identity="carol@fund.example", deals=["Atlas"])
    outsider = key(tid, role="associate", identity="bob@fund.example")
    return tid, {"walled": walled, "group": group_member, "scoped": scoped, "outsider": outsider}


def set_wall(tid, grants):
    with SessionLocal() as db:
        bind_tenant(db, tid)
        d = db.query(Deal).filter_by(tenant_id=tid, name="Atlas").one()
        d.wall = format_wall(grants)
        db.commit()


def principal(tid, headers):
    with SessionLocal() as db:
        bind_tenant(db, tid)
        return principal_for_key(db, headers["Authorization"].split()[1])


def test_format_wall_normalises_and_empty_is_no_wall():
    assert format_wall([" Alice@Fund.example ", "", "alice@fund.example"]) == '["alice@fund.example"]'
    assert format_wall(["group:Deal-Team"]) == '["group:deal-team"]'
    assert format_wall([]) is None
    assert format_wall([" "]) is None
    assert parse_wall(None) == ()
    assert parse_wall('["a","b"]') == ("a", "b")


def test_a_walled_identity_cannot_see_the_deal_its_documents_or_its_name_in_scope():
    tid, keys = setup("walls-identity")
    set_wall(tid, ["alice@fund.example"])
    with SessionLocal() as db:
        bind_tenant(db, tid)
        alice = principal(tid, keys["walled"])
        bob = principal(tid, keys["outsider"])
        assert hidden_deal_names(db, alice) == {"Atlas"}
        assert deal_scope(db, alice) == {"Beta"}  # unscoped key: every deal except the walled one
        atlas = db.query(Deal).filter_by(tenant_id=tid, name="Atlas").one()
        assert deal_hidden(atlas, alice) and not deal_hidden(atlas, bob)
        alice_docs = visible_doc_ids(db, alice)
        assert alice_docs is not None and len(alice_docs) == 1  # the Beta document only
        assert hidden_deal_names(db, bob) == frozenset()
        assert visible_doc_ids(db, bob) is None


def test_a_wall_on_a_group_hides_the_deal_from_every_member():
    tid, keys = setup("walls-group")
    set_wall(tid, ["group:deal-team"])
    with SessionLocal() as db:
        bind_tenant(db, tid)
        assert "Atlas" in hidden_deal_names(db, principal(tid, keys["group"]))
        assert "Atlas" not in hidden_deal_names(db, principal(tid, keys["outsider"]))


def test_a_wall_overrides_deal_scope_on_a_scoped_key():
    tid, keys = setup("walls-scoped")
    set_wall(tid, ["carol@fund.example"])
    with SessionLocal() as db:
        bind_tenant(db, tid)
        carol = principal(tid, keys["scoped"])
        assert deal_scope(db, carol) == set()
        assert visible_doc_ids(db, carol) == set()  # Atlas was her only deal, and it is walled from her


def test_a_wall_is_not_enforced_by_name_matching():
    tid, keys = setup("walls-name")
    set_wall(tid, ["alice@fund.example"])
    with SessionLocal() as db:
        bind_tenant(db, tid)
        bob = principal(tid, keys["outsider"])
        assert mnpi_name_conflict(db, bob, "Atlas") is False
        assert visible_mnpi_deal_names(db, bob) == []  # no MNPI deals here; walls do not add any


def test_an_mnpi_deal_that_is_also_walled_stays_hidden_from_its_walled_scoped_key():
    tid, keys = setup("walls-mnpi")
    with SessionLocal() as db:
        bind_tenant(db, tid)
        db.query(Deal).filter_by(tenant_id=tid, name="Atlas").one().mnpi = True
        db.commit()
    set_wall(tid, ["carol@fund.example"])
    with SessionLocal() as db:
        bind_tenant(db, tid)
        carol = principal(tid, keys["scoped"])
        assert "Atlas" in hidden_deal_names(db, carol)
        assert visible_mnpi_deal_names(db, carol) == []


def test_removing_the_wall_restores_access():
    tid, keys = setup("walls-remove")
    set_wall(tid, ["alice@fund.example"])
    set_wall(tid, [])
    with SessionLocal() as db:
        bind_tenant(db, tid)
        assert hidden_deal_names(db, principal(tid, keys["walled"])) == frozenset()

