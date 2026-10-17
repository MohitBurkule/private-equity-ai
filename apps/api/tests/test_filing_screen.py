from decimal import Decimal
from types import SimpleNamespace

from app import alerts, secfeed
from app.alerts import new_target_screen, screening_criteria, sec_filings

ATOM = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <category term="8-K" label="form type" scheme="http://www.sec.gov/"/>
  <content type="text/xml"><accession-number>0001234567-26-000111</accession-number></content>
  <link rel="alternate" href="https://www.sec.gov/Archives/edgar/data/1234567/000123456726000111/0001234567-26-000111-index.htm"/>
  <title>8-K - ACME CORP (0001234567) (Filer)</title>
  <updated>2026-10-16T17:02:11-04:00</updated>
 </entry>
 <entry>
  <category term="4" label="form type" scheme="http://www.sec.gov/"/>
  <content type="text/xml"><accession-number>0001234567-26-000112</accession-number></content>
  <link rel="alternate" href="https://www.sec.gov/Archives/edgar/data/1234567/000123456726000112/0001234567-26-000112-index.htm"/>
  <updated>2026-10-15T09:00:00-04:00</updated>
 </entry>
</feed>"""


class FakeDb:
    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        return self

    def filter_by(self, **kw):
        return [r for r in self.rows if all(getattr(r, k) == v for k, v in kw.items() if k in ("status", "source"))]


def test_atom_keeps_interesting_forms_with_index_url():
    got = secfeed.parse_atom(ATOM)
    assert [(e.form, e.accession, e.filed) for e in got] == [("8-K", "0001234567-26-000111", "2026-10-16")]
    assert got[0].url.endswith("0001234567-26-000111-index.htm")
    assert secfeed.feed_url("1234567").startswith("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001234567")


def test_filing_watch_alerts_on_watched_sec_targets_only(monkeypatch):
    acme = SimpleNamespace(id=1, name="Acme", source="sec", source_ref="1234567", status="watching")
    down = SimpleNamespace(id=2, name="Down", source="sec", source_ref="999", status="watching")
    other = SimpleNamespace(id=3, name="Idle", source="sec", source_ref="1234567", status="new")

    def fetch(url):
        if "CIK=0000000999" in url:
            raise OSError("feed down")
        return ATOM.encode()

    monkeypatch.setattr(alerts, "sec_fetch", fetch)
    out = sec_filings(FakeDb([acme, down, other]), "t")
    assert len(out) == 1 and out[0].dedupe_key == "filing:0001234567-26-000111"
    assert out[0].title == "Acme: new 8-K filed 2026-10-16"
    assert "-index.htm" in out[0].detail


def test_screening_criteria_parsed_from_plain_rule():
    c = screening_criteria("Sectors: software, fintech. Minimum revenue 20,000,000 USD.")
    assert c.sectors == ["software", "fintech"] and c.min_revenue == Decimal(20000000)
    assert screening_criteria("We like good businesses").sectors == []


def test_screen_alerts_only_matches_with_known_fit(monkeypatch):
    quote = "Sectors: software. Minimum revenue 20000000"
    rule = SimpleNamespace(value=quote, document_id=3, page=1, quote=quote)
    monkeypatch.setattr(alerts.fk, "newest_accepted", lambda db, t, k: rule)
    fit = SimpleNamespace(id=10, name="Fit", sector="Enterprise Software", country=None, revenue=Decimal(30000000),
                          source_url="https://www.sec.gov/x", source_ref="1", status="new")
    small = SimpleNamespace(id=11, name="Small", sector="Software", country=None, revenue=Decimal(5000000),
                            source_url=None, source_ref="2", status="new")
    unknown = SimpleNamespace(id=12, name="Unknown", sector="Software", country=None, revenue=None,
                              source_url=None, source_ref="3", status="new")
    out = new_target_screen(FakeDb([fit, small, unknown]), "t")
    assert [d.dedupe_key for d in out] == ["screen:10"]
    assert "https://www.sec.gov/x" in out[0].detail and quote in out[0].detail


def test_no_rule_no_screen(monkeypatch):
    monkeypatch.setattr(alerts.fk, "newest_accepted", lambda db, t, k: None)
    assert new_target_screen(FakeDb([]), "t") == []
