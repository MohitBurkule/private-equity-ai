"""Runs only against Postgres (set DATABASE_URL to the app role, MIGRATE_DATABASE_URL to the owner).

Raw SQL as the app role, bypassing every app-level filter: RLS alone must hold.
"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

URL = os.environ.get("RLS_TEST_APP_URL", "")
pytestmark = pytest.mark.skipif(not URL.startswith("postgresql"), reason="needs Postgres")


@pytest.fixture(scope="module")
def eng():
    from app.db import Base
    from app.rls import apply_rls
    owner = create_engine(os.environ["RLS_TEST_OWNER_URL"])
    import app.audit
    import app.models
    import app.portfolio  # noqa: F401
    Base.metadata.drop_all(owner)
    Base.metadata.create_all(owner)
    apply_rls(owner, os.environ["RLS_TEST_APP_ROLE"])
    return create_engine(URL)


def insert_doc(c, tenant, doc_id, row_tenant=None):
    c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant})
    c.execute(text("INSERT INTO document (id, tenant_id, sha256, filename, n_pages, kind) "
                   "VALUES (:i, :t, 's', 'f', 1, 'pdf')"), {"i": doc_id, "t": row_tenant or tenant})


def test_rls_isolates_rows_even_for_raw_sql(eng):
    with eng.begin() as c:
        insert_doc(c, "A", "doc-a")
    with eng.begin() as c:
        insert_doc(c, "B", "doc-b")
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', 'A', true)"))
        assert [r[0] for r in c.execute(text("SELECT id FROM document"))] == ["doc-a"]
        assert c.execute(text("DELETE FROM document WHERE id='doc-b'")).rowcount == 0
        assert c.execute(text("UPDATE document SET filename='x' WHERE id='doc-b'")).rowcount == 0


def test_no_tenant_set_means_no_rows(eng):
    with eng.begin() as c:
        assert c.execute(text("SELECT count(*) FROM document")).scalar() == 0


def test_cannot_insert_row_for_another_tenant(eng):
    with pytest.raises(DBAPIError), eng.begin() as c:
        insert_doc(c, "A", "doc-evil", row_tenant="B")


def test_child_rows_follow_parent(eng):
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', 'A', true)"))
        c.execute(text("INSERT INTO page (document_id, number, text) VALUES ('doc-a', 1, 'hello')"))
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', 'B', true)"))
        assert c.execute(text("SELECT count(*) FROM page")).scalar() == 0
        with pytest.raises(DBAPIError):
            c.execute(text("INSERT INTO page (document_id, number, text) VALUES ('doc-a', 2, 'x')"))


def test_setting_does_not_leak_across_transactions(eng):
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', 'A', true)"))
    with eng.begin() as c:
        assert c.execute(text("SELECT count(*) FROM document")).scalar() == 0


def test_app_role_is_unprivileged(eng):
    from app.rls import verify_app_role
    verify_app_role(eng)
