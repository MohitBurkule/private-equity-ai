"""Postgres only: migrations build the schema, and models have not drifted from migrations."""
import os

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

OWNER = os.environ.get("RLS_TEST_OWNER_URL", "")
pytestmark = pytest.mark.skipif(not OWNER.startswith("postgresql"), reason="needs Postgres")


def test_migrations_match_models_and_are_idempotent():
    import app.audit
    import app.models
    import app.portfolio  # noqa: F401
    from app.db import Base
    from app.migrate import migrate
    # isolated schema so this test cannot disturb tables used by the rest of the suite
    admin = create_engine(OWNER)
    with admin.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS mig_test CASCADE"))
        c.execute(text("CREATE SCHEMA mig_test"))
    # search_path goes in the URL (not connect_args) so Alembic, which rebuilds its own engine
    # from the URL, targets the same schema
    eng = create_engine(make_url(OWNER).update_query_dict({"options": "-csearch_path=mig_test"}))
    migrate(eng)
    migrate(eng)  # second run is a no-op
    with eng.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata)
    with admin.begin() as c:
        c.execute(text("DROP SCHEMA mig_test CASCADE"))
    assert diff == [], f"models drifted from migrations: {diff}"
