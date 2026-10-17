from fastapi.testclient import TestClient

from app.main import SessionLocal, app
from app.models import Fact
from app.rls import bind_tenant
from tests.helpers import new_tenant_id
from tests.test_review import mk, upload

c = TestClient(app)


def unreviewed(tid, ids, status="auto"):
    """Manual facts are created verified. Extraction makes auto and ocr_unverified rows, so set those the same way."""
    with SessionLocal() as db:
        bind_tenant(db, tid)
        for i in ids:
            db.get(Fact, i).status = status
        db.commit()


def test_queue_lists_unreviewed_and_ocr_facts_with_counts_and_evidence():
    h, tid = new_tenant_id(c, "queue-counts")
    doc = upload(h)
    f1 = mk(h, doc)
    f2 = mk(h, doc, "ebitda", "321", "Sheet!B2: 321")
    unreviewed(tid, [f1, f2])
    body = c.get("/facts/review-queue", headers=h).json()
    assert body["total"] == 2 and body["counts"] == {"auto": 2, "ocr_unverified": 0}
    assert [i["id"] for i in body["items"]] == [f1, f2]
    assert body["items"][0]["sources"][0]["quote"] == "Sheet!B1: 1,234"  # the evidence sits beside the value


def test_a_reviewed_fact_leaves_the_queue_and_limit_pages_the_items_not_the_counts():
    h, tid = new_tenant_id(c, "queue-review")
    doc = upload(h)
    ids = [mk(h, doc, f"m{i}", "1", "Sheet!B1: 1,234") for i in range(3)]
    unreviewed(tid, ids)
    c.post(f"/facts/{ids[0]}/review", headers=h, json={"action": "accept"})
    body = c.get("/facts/review-queue", params={"limit": 1}, headers=h).json()
    assert body["total"] == 2 and body["counts"]["auto"] == 2
    assert len(body["items"]) == 1 and body["items"][0]["id"] == ids[1]


def test_queue_is_scoped_to_the_callers_entity():
    h, tid = new_tenant_id(c, "queue-entity")
    doc = upload(h)
    unreviewed(tid, [mk(h, doc)])  # entity "A"
    assert c.get("/facts/review-queue", params={"entity": "B"}, headers=h).json()["total"] == 0
    assert c.get("/facts/review-queue", params={"entity": "A"}, headers=h).json()["total"] == 1
