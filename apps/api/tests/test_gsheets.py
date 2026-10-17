"""Google Sheets two-way sync against a local fake of the Sheets v4 API (synthetic values, no real sheet)."""
import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.main as m
from app.connectors.base import ConnectorError
from app.connectors.gsheets import GoogleSheets
from app.db import Base, make_engine
from app.factsxlsx import fact_rows
from app.main import app
from app.models import Document, Fact, FactSource
from tests.helpers import new_tenant

c = TestClient(app)
SID = "1AbCdEfGhIjKlMnOp"


class FakeSheets:
    """Serves one tab on GET and records the last batchUpdate body on POST."""

    def __init__(self, values):
        self.values, self.posted = values, None

    def __call__(self, url, headers):
        assert headers["Authorization"] == "Bearer tok"
        if "X-Post-Body" in headers:
            assert url.endswith(f"/{SID}/values:batchUpdate")
            self.posted = json.loads(headers["X-Post-Body"])
            return json.dumps({"totalUpdatedCells": sum(len(r) for r in self.posted["data"][0]["values"])}).encode()
        assert url.startswith(f"https://sheets.googleapis.com/v4/spreadsheets/{SID}/values/")
        return json.dumps({"range": "Deals!A1:B2", "values": self.values}).encode()


def test_pull_tab_becomes_cited_csv_and_is_versioned():
    fake = FakeSheets([["Deal", "EV"], ["Atlas", "900"]])
    conn = GoogleSheets("tok", fake, spreadsheet=SID, range="Deals")
    (item,) = list(conn.items())
    assert item.name == "gsheets-Deals.csv"
    assert item.data == b"Deal,EV\r\nAtlas,900\r\n"
    assert item.url == f"https://docs.google.com/spreadsheets/d/{SID}/edit"
    assert item.external_id == f"gsheets:{SID}:Deals"


def test_empty_tab_yields_nothing_and_bad_id_is_refused():
    assert list(GoogleSheets("tok", FakeSheets([]), spreadsheet=SID).items()) == []
    try:
        list(GoogleSheets("tok", FakeSheets([]), spreadsheet="../etc").items())
    except ConnectorError:
        pass
    else:
        raise AssertionError("bad spreadsheet id accepted")


def test_push_writes_rows_to_the_range():
    fake = FakeSheets([])
    conn = GoogleSheets("tok", fake, spreadsheet=SID, range="Facts")
    assert conn.push([["Entity", "Value"], ["Acme", 1200.0]]) == 4
    assert fake.posted == {"valueInputOption": "RAW", "data": [{"range": "Facts",
                           "values": [["Entity", "Value"], ["Acme", 1200.0]]}]}


def test_fact_rows_keep_scope_and_headers():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Document(id="d1", tenant_id="t", sha256="a", filename="cim.pdf", n_pages=1, kind="pdf", deal="atlas"))
        s.flush()
        f = Fact(tenant_id="t", entity="Acme", metric="revenue", period="FY2024", value=1200, unit="USD_m",
                 status="verified")
        f.sources.append(FactSource(document_id="d1", page=1, quote="Revenue 1,200"))
        s.add(f)
        s.flush()
        rows = fact_rows(s, "t", None, scope={"d1"})
        assert fact_rows(s, "t", None, scope=set()) == [rows[0]]  # no visible facts: headers only
    assert rows[0][:4] == ["Entity", "Metric", "Period", "Value"]
    assert rows[1][:4] == ["Acme", "revenue", "FY2024", 1200.0]


def test_push_endpoint_validates_and_writes(monkeypatch):
    h = new_tenant(c, "gsheets")
    r = c.post("/connectors/gsheets/push", json={"token": "tok", "spreadsheet": "../x"}, headers=h)
    assert r.status_code == 422
    fake = FakeSheets([])
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake)
    r = c.post("/connectors/gsheets/push", json={"token": "tok", "spreadsheet": SID, "range": "Facts"}, headers=h)
    assert r.status_code == 200
    assert fake.posted["data"][0]["values"][0] == ["Entity", "Metric", "Period", "Value", "Unit", "Basis",
                                                    "Status", "Reviewed by"]
