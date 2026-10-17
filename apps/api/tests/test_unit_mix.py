"""One metric, entity, period and basis carries one unit. A second unit is refused, not stored beside the first."""
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db import Base, make_engine
from app.facts import CitationError, add_verified_fact
from app.models import Document, PageRow

PAGE = "Statement (in millions)\nTotal revenues 1,000\n"


def _session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    d = Document(id="u" * 64, tenant_id="t", sha256="s", filename="acme.pdf", n_pages=1)
    d.pages = [PageRow(number=1, text=PAGE)]
    s.add(d)
    s.commit()
    return s, d.id


def _kw(doc: str, unit: str) -> dict:
    return {"tenant_id": "t", "entity": "Acme", "metric": "revenue", "period": "FY24", "unit": unit,
            "document_id": doc, "page": 1, "quote": "Total revenues 1,000", "value": Decimal(1000)}


def test_second_unit_for_the_same_metric_and_period_is_refused():
    s, doc = _session()
    add_verified_fact(s, **_kw(doc, "USD"))
    with pytest.raises(CitationError, match="conflicts with existing USD"):
        add_verified_fact(s, **_kw(doc, "GBP"))


def test_same_unit_again_and_other_periods_are_fine():
    s, doc = _session()
    add_verified_fact(s, **_kw(doc, "USD"))
    add_verified_fact(s, **_kw(doc, "USD"))
    add_verified_fact(s, **{**_kw(doc, "GBP"), "period": "FY25"})
