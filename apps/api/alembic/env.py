import os

from sqlalchemy import create_engine

import app.audit
import app.models
import app.portfolio  # noqa: F401
from alembic import context
from app.db import Base

target_metadata = Base.metadata


def _url() -> str:
    return (context.config.get_main_option("sqlalchemy.url") or os.environ.get("MIGRATE_DATABASE_URL")
            or os.environ["DATABASE_URL"])


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
