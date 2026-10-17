from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app import derived
from app.db import Base, make_engine
from app.facts import add_verified_fact
from app.models import Document, PageRow

PAGE = "Operating income 100\nDepreciation and amortization 20\nRevenue 900"


def setup_db():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    d = Document(id="e" * 64, tenant_id="t", sha256="s", filename="acme.pdf", n_pages=1)
    d.pages = [PageRow(number=1, text=PAGE)]
    s.add(d)
    s.commit()
    return s, d.id


def fact(s, doc, metric, value, quote, unit="USD"):
    add_verified_fact(s, tenant_id="t", entity="Acme", metric=metric, period="FY24", value=Decimal(value),
                      unit=unit, document_id=doc, page=1, quote=quote)


def test_ebitda_is_the_sum_of_cited_components_and_keeps_each_citation():
    s, doc = setup_db()
    fact(s, doc, "operating_income", 100, "Operating income 100")
    fact(s, doc, "depreciation_and_amortization", 20, "Depreciation and amortization 20")
    d = derived.derive(s, "t", None, "ebitda", "Acme", "FY24")
    assert d.value == Decimal(120) and d.unit == "USD"
    assert [c.metric for c in d.components] == ["operating_income", "depreciation_and_amortization"]
    assert all(c.sources and c.sources[0]["page"] == 1 for c in d.components)


def test_refuses_a_missing_component_and_mixed_units():
    s, doc = setup_db()
    fact(s, doc, "operating_income", 100, "Operating income 100")
    with pytest.raises(ValueError, match="depreciation_and_amortization"):
        derived.derive(s, "t", None, "ebitda", "Acme", "FY24")
    fact(s, doc, "depreciation_and_amortization", 20, "Depreciation and amortization 20", unit="EUR")
    with pytest.raises(ValueError, match="different units"):
        derived.derive(s, "t", None, "ebitda", "Acme", "FY24")
    with pytest.raises(ValueError, match="unknown formula"):
        derived.derive(s, "t", None, "nonsense", "Acme", "FY24")
