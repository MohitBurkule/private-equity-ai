"""Email-to-deal linker. An ingested email is linked to a deal when its text names the deal's company, or
mentions the company's website domain. Each link carries the email's source link, so it can be cited.
Matching is on the text the email was ingested with, and nothing is stored: links are computed on read,
so they always follow the current deals, targets and visibility rules."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.acl import Principal, hidden_deal_names, visible_doc_ids
from app.models import Deal, Document, DocumentSource, Target

EMAIL_CONNECTORS = ("gmail", "outlook", "imap", "mailpit")


def _domain(website: str | None) -> str | None:
    host = (urlparse(website or "").hostname or "").lower()
    return host.removeprefix("www.") or None


def company_terms(deal_name: str, targets: list[Target]) -> list[tuple[str, str]]:
    """(kind, term) pairs for one deal: its name, and the website domain of a target with the same name."""
    terms = [("name", deal_name)]
    for t in targets:
        domain = _domain(t.website)
        if domain and t.name.lower() == deal_name.lower():
            terms.append(("domain", domain))
    return terms


def _hit(text: str, kind: str, term: str) -> bool:
    if kind == "name":
        # not inside an address or domain: "atlas.test" and "x@atlas" name a domain, not the company
        return re.search(rf"(?<![\w@.]){re.escape(term)}(?!\w|@|\.\w)", text, re.IGNORECASE) is not None
    return re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", text, re.IGNORECASE) is not None


def find_links(deals: list[str], targets: list[Target], emails: list[dict]) -> list[dict]:
    """One link per (deal, email): the first term that matches, names before domains."""
    out = []
    for deal in deals:
        terms = company_terms(deal, targets)
        for e in emails:
            for kind, term in terms:
                if _hit(e["text"], kind, term):
                    out.append({"deal": deal, "document_id": e["document_id"], "filename": e["filename"],
                                "source_url": e["source_url"], "matched_on": kind, "term": term})
                    break
    return out


def email_documents(db: Session, tenant_id: str, scope: set[str] | None) -> list[dict]:
    srcs = db.query(DocumentSource).filter(DocumentSource.tenant_id == tenant_id,
                                           DocumentSource.connector.in_(EMAIL_CONNECTORS)).all()
    src_by_doc = {s.document_id: s.url for s in srcs if scope is None or s.document_id in scope}
    if not src_by_doc:
        return []
    docs = db.query(Document).filter(Document.tenant_id == tenant_id, Document.id.in_(list(src_by_doc))).all()
    return [{"document_id": d.id, "filename": d.filename, "source_url": src_by_doc[d.id],
             "text": "\n".join(p.text for p in sorted(d.pages, key=lambda p: p.number))} for d in docs]


def links_for(db: Session, who: Principal) -> list[dict]:
    """Links the caller may see: only visible emails, and only deals the caller may see."""
    hidden = hidden_deal_names(db, who)
    deals = [d.name for d in db.query(Deal).filter_by(tenant_id=who.tenant).all() if d.name not in hidden]
    targets = db.query(Target).filter_by(tenant_id=who.tenant).all()
    emails = email_documents(db, who.tenant, visible_doc_ids(db, who))
    return find_links(deals, targets, emails)
