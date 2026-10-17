# Contributing

- Run the checks CI runs before pushing: `cd apps/api && ruff check . && ruff format --check . && pytest -q`.
- One migration per PR. Alembic keeps one head: `apps/api/tests/test_alembic_heads.py` fails on a clash.
- New dependencies: add them to `apps/api/pyproject.toml`, then regenerate `docs/LICENSES.md` with `python scripts/licence_audit.py > docs/LICENSES.md`. Copyleft or unknown licences need a reviewer's sign-off.
- Facts shown to users must cite a source. Changes to extraction or answering need a golden-set check (`apps/api/tests/golden`).
- Licence: AGPL-3.0 (see `LICENSE`).
