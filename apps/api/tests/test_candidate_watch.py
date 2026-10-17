import hashlib
from decimal import Decimal

from fastapi.testclient import TestClient

from app import alerts as al
from app import workflows as wf
from app.main import SessionLocal, app
from app.models import Alert, Document, FirmKnowledge, Target, WorkflowSchedule
from app.rls import bind_tenant

c = TestClient(app)
RULE = ("we review a deal only if revenue is at least $20 million, EBITDA margin is at least 15%, and the "
        "company operates in software or business services in the United States or Canada.")


def test_criteria_read_from_plain_rule():
    k = al.screening_criteria(RULE)
    assert k.sectors == ["software", "business services"] and k.countries == ["United States", "Canada"]
    assert k.min_revenue == Decimal(20_000_000)
    assert al.screening_criteria("We like good businesses").sectors == []


def tenant(name):
    r = c.post("/admin/tenants", json={"name": name}, headers={"X-Admin-Token": "test-admin"}).json()
    return {"Authorization": f"Bearer {r['api_key']}"}, r["tenant_id"]


def _seed(tid):
    with SessionLocal() as s:
        bind_tenant(s, tid)
        doc_id = hashlib.sha256(f"criteria:{tid}".encode()).hexdigest()
        s.add(Document(id=doc_id, tenant_id=tid, sha256=doc_id, filename="criteria.pdf", n_pages=1, kind="pdf"))
        s.flush()
        s.add(FirmKnowledge(tenant_id=tid, key="deal_screening_criteria", value=RULE, document_id=doc_id,
                            page=1, quote=RULE, status="accepted"))
        s.add(Target(tenant_id=tid, name="Imported Software Ltd", source="manual", source_ref="imp"))
        s.commit()


def test_candidates_dedupe_by_company_and_skip_imported(monkeypatch):
    _, tid = tenant("cw1")
    _seed(tid)
    edgar = lambda term, since, until: [("Acme Software, Inc.", "https://sec/acme", "SEC EDGAR filing"),
                                        ("Imported Software Ltd", "https://sec/imp", "SEC EDGAR filing")]
    ch = lambda term, since, until: [("ACME SOFTWARE LTD", "https://ch/acme", "Companies House company page"),
                                     ("Beta Services Limited", "https://ch/beta", "Companies House company page")]
    with SessionLocal() as s:
        bind_tenant(s, tid)
        made = al.scan_candidates(s, tid, edgar, ch, "2026-10-10", "2026-10-17")
        titles = sorted(a.title for a in made)
        assert titles == ["New candidate: Acme Software, Inc.", "New candidate: Beta Services Limited"]
        assert all("Revenue not checked" in a.detail and "https://" in a.detail for a in made)
        again = al.scan_candidates(s, tid, edgar, ch, "2026-10-10", "2026-10-17")
        assert again == []  # nothing repeats on the next run
        assert s.query(Alert).filter_by(tenant_id=tid, kind="candidate").count() == 2


def test_failed_source_is_skipped():
    _, tid = tenant("cw2")
    _seed(tid)

    def broken(term, since, until):
        raise OSError("down")
    ch = lambda term, since, until: [("Gamma Tech Ltd", "https://ch/g", "Companies House company page")]
    with SessionLocal() as s:
        bind_tenant(s, tid)
        made = al.scan_candidates(s, tid, broken, ch, "2026-10-10", "2026-10-17")
        assert [a.title for a in made] == ["New candidate: Gamma Tech Ltd"]


def test_weekly_schedule_mails_new_candidates_once(monkeypatch):
    _, tid = tenant("cw4")
    _seed(tid)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    found = [[("Zeta Cloud Ltd", "https://ch/z", "Companies House company page")], []]
    monkeypatch.setattr(wf, "_ch_candidates", lambda term, since, until: found.pop(0) if found else [])
    sent = []
    from datetime import UTC, datetime, timedelta
    t0 = datetime(2026, 10, 17, tzinfo=UTC)
    with SessionLocal() as s:
        bind_tenant(s, tid)
        wf.create(s, tid, "weekly candidates", "candidate_watch", 7, {}, ["ops@example.com"], start=t0)
        wf.run_due(s, tid, None, mailer=lambda to, subj, body: sent.append(body), now=t0)
        assert len(sent) == 1 and "Zeta Cloud Ltd" in sent[0]
        wf.run_due(s, tid, None, mailer=lambda to, subj, body: sent.append(body), now=t0 + timedelta(days=7))
        assert len(sent) == 1  # nothing new the second week: no mail


def test_screen_without_criteria_uses_cited_profile():
    h, tid = tenant("cw3")
    assert c.post("/targets/screen", headers=h, json={}).status_code == 422  # no rule accepted yet
    _seed(tid)
    c.post("/targets", headers=h, json=[{"name": "Delta", "source_ref": "d", "sector": "Software",
                                         "country": "Canada", "revenue": "50000000", "revenue_url": "http://r"}])
    r = c.post("/targets/screen", headers=h, json={}).json()
    assert r["applied"]["sectors"] == ["software", "business services"]
    assert r["applied"]["min_revenue"] == "20000000"
    assert r["criteria_source"]["quote"] == RULE


def test_seed_script_creates_one_weekly_schedule(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    from app.db import Base, make_engine
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/seed.db")
    _, tid = tenant("cw5")
    spec = importlib.util.spec_from_file_location("seedcw", Path(__file__).resolve().parents[1] / "scripts/seed_candidate_watch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    Base.metadata.create_all(make_engine())
    assert mod.main([tid]) == 0
    assert mod.main([tid]) == 0  # idempotent
    from sqlalchemy.orm import sessionmaker
    with sessionmaker(bind=make_engine())() as s:
        rows = s.query(WorkflowSchedule).filter_by(tenant_id=tid, kind="candidate_watch").all()
        assert len(rows) == 1 and rows[0].recipients == "candidates@mailpit.local" and rows[0].every_days == 7
