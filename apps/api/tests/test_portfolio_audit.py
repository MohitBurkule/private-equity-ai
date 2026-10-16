from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.audit import log_event, verify_chain
from app.db import Base, make_engine
from app.facts import add_verified_fact
from app.models import Document, Fact, PageRow
from app.portfolio import PortfolioCompany, current_kpis, qoq_change, record_observation


def make_db():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    d = Document(id="e" * 64, tenant_id="t", sha256="s", filename="q.pdf", n_pages=1)
    d.pages = [PageRow(number=1, text="Revenue 100\nRevenue restated 110\nRevenue prior 80\n")]
    s.add(d)
    c = PortfolioCompany(tenant_id="t", name="Acme")
    s.add(c)
    s.commit()
    return s, d.id, c.id


def fact(s, doc, period, value, quote):
    return add_verified_fact(s, tenant_id="t", entity="Acme", metric="revenue", period=period,
                             value=Decimal(value), unit="USD", document_id=doc, page=1, quote=quote)


def test_observation_requires_verified_cited_fact():
    s, _doc, cid = make_db()
    bare = Fact(tenant_id="t", entity="Acme", metric="revenue", period="Q1", value=1, unit="USD")
    s.add(bare)
    s.commit()
    with pytest.raises(ValueError):
        record_observation(s, "t", cid, bare.id)
    with pytest.raises(ValueError):
        record_observation(s, "t", cid, 9999)


def test_restatement_supersedes_but_history_kept_and_change_in_code():
    s, doc, cid = make_db()
    record_observation(s, "t", cid, fact(s, doc, "Q1", 100, "Revenue 100").id)
    record_observation(s, "t", cid, fact(s, doc, "Q0", 80, "Revenue prior 80").id)
    assert qoq_change(s, "t", cid, "revenue", "Q1", "Q0") == Decimal(25)
    record_observation(s, "t", cid, fact(s, doc, "Q1", 110, "Revenue restated 110").id)
    cur = {o.period: o.value for o in current_kpis(s, "t", cid)}
    assert cur["Q1"] == Decimal(110)
    assert s.execute(text("select count(*) from kpi_observation")).scalar() == 3
    assert qoq_change(s, "t", cid, "revenue", "Q1", "Missing") is None


def test_audit_chain_detects_tampering():
    s, *_ = make_db()
    for i in range(3):
        log_event(s, "t", "u", "x", {"i": i})
    assert verify_chain(s, "t") == (True, None)
    s.execute(text("update audit_event set payload='{\"i\": 99}' where id=2"))
    s.commit()
    assert verify_chain(s, "t") == (False, 2)
