"""Email routing: an unattached email goes to the one deal it names (by name, alias, CIK, LEI or domain), else to
the review queue. MNPI deals are never a target, and a person can attach a queued email by hand."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.main as m
from app.db import Base, make_engine
from app.email_routing import deal_terms, matched_deals, route_emails
from app.main import app
from app.models import Deal, Document, DocumentSource, PageRow, Target
from tests.helpers import new_tenant
from tests.test_mailpit_ingest import BASE, FakeMailpit, raw_mail

c = TestClient(app)


def _doc(s: Session, did: str, text: str) -> Document:
    d = Document(
        id=did,
        tenant_id="t",
        sha256=did,
        filename=f"{did}.eml",
        n_pages=1,
        kind="eml",
        deal=None,
    )
    s.add(d)
    s.add(PageRow(document_id=did, number=1, text=text))
    s.add(
        DocumentSource(
            tenant_id="t",
            document_id=did,
            connector="imap",
            external_id=did,
            version="v1",
            url=did,
        )
    )
    return d


def _deals(s: Session) -> None:
    s.add(Deal(tenant_id="t", name="Atlas", aliases="Atlas Holdings, Project Blue"))
    s.add(
        Deal(
            tenant_id="t", name="Borealis", cik="0001234567", lei="5493001KJTIIGC8Y1R12"
        )
    )
    s.add(Deal(tenant_id="t", name="Secret", mnpi=True))
    s.add(
        Target(
            tenant_id="t",
            name="Cascade",
            source="manual",
            source_ref="c",
            website="https://www.cascade.test",
        )
    )
    s.add(Deal(tenant_id="t", name="Cascade"))


def _session() -> Session:
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_each_identifier_routes_to_its_one_deal():
    with _session() as s:
        _deals(s)
        s.flush()
        targets = s.query(Target).all()
        deals = [
            (d.name, deal_terms(d, targets))
            for d in s.query(Deal).filter_by(mnpi=False)
        ]
        assert matched_deals("Re: Project Blue term sheet", deals) == {"Atlas"}
        assert matched_deals("Atlas Holdings wants a call", deals) == {"Atlas"}
        assert matched_deals("Filer CIK 0001234567 files 10-K", deals) == {"Borealis"}
        assert matched_deals("Filer CIK 1234567 files 10-K", deals) == {"Borealis"}
        assert matched_deals("LEI 5493001KJTIIGC8Y1R12 on file", deals) == {"Borealis"}
        assert matched_deals("note from ops@cascade.test", deals) == {"Cascade"}
        assert matched_deals("nothing relevant here", deals) == set()


def test_ambiguous_or_unknown_stays_for_review_and_mnpi_is_never_a_target():
    with _session() as s:
        _deals(s)
        _doc(s, "two", "Atlas and Borealis both in the email")
        _doc(s, "none", "lunch on friday")
        _doc(s, "secret", "Secret deal update")
        _doc(s, "owned", "Atlas again")
        s.query(Document).filter_by(id="owned").one().deal = "Borealis"
        s.flush()
        docs = (
            s.query(Document)
            .filter(Document.id.in_(["two", "none", "secret", "owned"]))
            .all()
        )
        out = route_emails(s, "t", docs)
        assert out["attached"] == []
        assert sorted(out["review"]) == ["none", "secret", "two"]
        assert s.query(Document).filter_by(id="owned").one().deal == "Borealis"


def test_sync_routes_then_queues_then_person_attaches(monkeypatch):
    monkeypatch.setattr(
        m,
        "CONNECTOR_HTTP",
        FakeMailpit(
            {
                "ab12": raw_mail(
                    "Project Blue", "Term sheet attached for Project Blue."
                ),
                "cd34": raw_mail("Lunch", "Friday at noon?"),
            }
        ),
    )
    h = new_tenant(c, "route")
    assert (
        c.post(
            "/deals", headers=h, json={"name": "Atlas", "aliases": ["Project Blue"]}
        ).status_code
        == 201
    )
    r = c.post("/connectors/mailpit/sync", json={"token": "local"}, headers=h)
    assert r.status_code == 200, r.text
    queued = c.get("/email/review", headers=h).json()["emails"]
    assert [e["filename"].endswith(".eml") for e in queued] == [True]
    assert queued[0]["source_url"] == f"{BASE}/view/cd34"
    attached = c.post(
        f"/email/review/{queued[0]['document_id']}/attach",
        headers=h,
        json={"deal": "Atlas"},
    )
    assert attached.status_code == 200, attached.text
    assert c.get("/email/review", headers=h).json() == {"emails": []}


def test_attach_to_unknown_deal_or_email_is_404():
    h = new_tenant(c, "route-scope")
    assert (
        c.post(
            "/email/review/nope/attach", headers=h, json={"deal": "Missing"}
        ).status_code
        == 404
    )
    assert c.get("/email/review", headers=h).json() == {"emails": []}
