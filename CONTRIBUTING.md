# Contributing

- Run `make ci` before merging. It runs ruff, the alembic heads check, pytest on SQLite, the full suite on Postgres, and web `tsc` + `vitest`. GitHub Actions is not the gate right now, so this is. Postgres needs a non-root user: `PG_RUN_AS=<user> make ci` (the script starts a throwaway embedded-postgres 18 cluster; see `scripts/test_postgres.sh`).
- `make test-postgres` alone runs the API suite on Postgres. Use it when you touch RLS, tenant binding or the ACL code.
- One migration per PR. Alembic keeps one head: `apps/api/tests/test_alembic_heads.py` fails on a clash.
- Migration revision ids are timestamps, not counters: `revision = '20261017_1636_short_slug'` (UTC, `YYYYMMDD_HHMM`, then a short slug), and the file is `20261017_1636_short_slug.py`. Set `down_revision` to the current head when you branch from main (check with `cd apps/api && alembic heads`). Older files keep their numbers. Two threads picking the same number can no longer share an id.
- New dependencies: add them to `apps/api/pyproject.toml`, then regenerate `docs/LICENSES.md` with `python scripts/licence_audit.py > docs/LICENSES.md`. Copyleft or unknown licences need a reviewer's sign-off.
- Facts shown to users must cite a source. Changes to extraction or answering need a golden-set check (`apps/api/tests/golden`).
- Licence: AGPL-3.0 (see `LICENSE`).
