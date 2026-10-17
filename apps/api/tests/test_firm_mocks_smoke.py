"""Smoke test for the SYNTHETIC firm-system stubs in deploy/mocks/wiremock/mappings (DealCloud, iManage, Datasite,
fund admin). Each stub must answer with its shape. Skipped unless WIREMOCK_JAR or WIREMOCK_URL is set.
The stubs are invented for tests; they are not copies of any vendor's API."""
import json
import urllib.request
from pathlib import Path

import pytest

from tests.mock_servers import WireMock

MAPPINGS = Path(__file__).resolve().parents[3] / "deploy" / "mocks" / "wiremock" / "mappings"
pytestmark = pytest.mark.skipif(not WireMock().available, reason="WIREMOCK_URL or WIREMOCK_JAR not set")

CASES = [
    ("/synthetic/dealcloud/v1/companies", "items"),
    ("/synthetic/dealcloud/v1/deals", "items"),
    ("/synthetic/imanage/v1/folders/F-77/documents", "items"),
    ("/synthetic/datasite/v1/rooms/R-42/files", "items"),
    ("/synthetic/fundadmin/v1/funds/FUND-7/capital-calls", "items"),
    ("/synthetic/fundadmin/v1/funds/FUND-7/nav", "nav_usd"),
]


@pytest.fixture(scope="module")
def wm():
    with WireMock() as w:
        for f in sorted(MAPPINGS.glob("*.json")):
            for m in json.loads(f.read_text())["mappings"]:
                req = urllib.request.Request(f"{w.base}/__admin/mappings", data=json.dumps(m).encode(), method="POST",
                                             headers={"content-type": "application/json"})
                urllib.request.urlopen(req, timeout=5).read()
        yield w


@pytest.mark.parametrize("path,key", CASES)
def test_stub_answers_with_its_shape(wm, path, key):
    body = json.loads(urllib.request.urlopen(wm.base + path, timeout=5).read())
    assert key in body
