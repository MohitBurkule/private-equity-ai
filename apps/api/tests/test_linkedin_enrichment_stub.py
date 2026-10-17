import pytest

from app.connectors.base import ConnectorError
from app.connectors.linkedin import LinkedInEnrichment


def test_enrichment_refuses_without_licence():
    with pytest.raises(ConnectorError, match="not licensed"):
        LinkedInEnrichment().company("Acme")


def test_enrichment_with_licence_is_still_unbuilt():
    with pytest.raises(NotImplementedError):
        LinkedInEnrichment(licence_key="x").company("Acme")
