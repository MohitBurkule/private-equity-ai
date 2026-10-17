"""Email-to-deal linker: name and domain matches, source links, the email-connector filter, and deal scope."""
from sqlalchemy.orm import Session

from app.acl import Principal
from app.db import Base, make_engine
from app.email_links import find_links, links_for
from app.models import Deal, Document, DocumentSource, PageRow, Target


def _doc(s: Session, did: str, name: str, text: str, connector: str | None, url: str = "") -> None:
    s.add(Document(id=did, tenant_id="t", sha256=did, filename=name, n_pages=1, kind="eml", deal=None))
    s.add(PageRow(document_id=did, number=1, text=text))
    if connector:
        s.add(DocumentSource(tenant_id="t", document_id=did, connector=connector, external_id=did,
                             version="v1", url=url))


def _seed(s: Session) -> None:
    s.add(Deal(tenant_id="t", name="Atlas"))
    s.add(Deal(tenant_id="t", name="Borealis"))
    s.add(Target(tenant_id="t", name="Atlas", source="manual", source_ref="a", website="https://www.atlas.test/about"))
    _doc(s, "e1", "gmail-1.eml", "Re: Atlas CIM, revenue was 1,234.", "gmail", "https://mail.google.com/#all/1")
    _doc(s, "e2", "imap-7.eml", "Covenant note from cfo@atlas.test today.", "imap", "imap://h/INBOX/7")
    _doc(s, "e3", "mailpit-9.eml", "Lunch on Friday?", "mailpit", "http://localhost:8025/view/9")
    _doc(s, "p1", "cim.pdf", "Atlas CIM page one.", None)  # a file, not an email: never linked


def test_name_and_domain_links_cite_each_email_once():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        _seed(s)
        s.flush()
        links = links_for(s, Principal(tenant="t"))
    got = sorted((ln["deal"], ln["document_id"], ln["matched_on"], ln["source_url"]) for ln in links)
    assert got == [
        ("Atlas", "e1", "name", "https://mail.google.com/#all/1"),
        ("Atlas", "e2", "domain", "imap://h/INBOX/7"),
    ]


def test_pure_matcher_word_boundaries_and_names_before_domains():
    lookalike = [{"document_id": "x", "filename": "x.eml", "source_url": "u", "text": "Atlasian software only."}]
    assert find_links(["Atlas"], [], lookalike) == []  # a longer word is not the company
    emails = [{"document_id": "x", "filename": "x.eml", "source_url": "u", "text": "Atlas Capital is raising."}]
    links = find_links(["Atlas"], [], emails)
    assert [(ln["matched_on"], ln["term"]) for ln in links] == [("name", "Atlas")]


def test_restricted_key_sees_only_its_deals_emails(monkeypatch):
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        _seed(s)
        s.flush()
        scoped = Principal(tenant="t", deals=frozenset({"Borealis"}))
        assert links_for(s, scoped) == []  # e1 and e2 are walled to no deal this key can see


def test_endpoint_returns_links_key_for_a_fresh_tenant():
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.helpers import new_tenant

    h = new_tenant(TestClient(app), "links")
    r = TestClient(app).get("/email-links", headers=h)
    assert r.status_code == 200 and r.json() == {"links": []}
