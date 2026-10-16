"""Schema management. Postgres uses Alembic migrations; SQLite (tests/dev) uses create_all."""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy.engine import Engine

from alembic import command
from app.db import Base


def migrate(owner_engine: Engine) -> None:
    if owner_engine.dialect.name != "postgresql":
        Base.metadata.create_all(owner_engine)
        return
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    cfg.set_main_option("sqlalchemy.url", owner_engine.url.render_as_string(hide_password=False)
                        .replace("%", "%%"))
    command.upgrade(cfg, "head")
