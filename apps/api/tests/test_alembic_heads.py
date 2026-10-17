"""Two threads adding a migration with the same number leave Alembic with two heads and a broken upgrade."""
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_single_alembic_head_and_unique_revisions():
    root = Path(__file__).parents[1]
    cfg = Config()
    cfg.set_main_option("script_location", str(root / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, f"multiple Alembic heads {heads}: renumber the newest migration so it follows the current head"
    revisions = [r.revision for r in script.walk_revisions()]
    files = list((root / "alembic" / "versions").glob("[0-9]*.py"))
    assert len(revisions) == len(set(revisions)) == len(files), f"revision ids clash or files missing: {sorted(revisions)}"
