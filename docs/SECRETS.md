# Secrets for the production stack

`docker-compose.prod.yml` reads every secret from the environment and refuses to start if one is missing.
No password is checked in. The dev compose file keeps its `change-me-*` values; never use them in production.

## What to set

| Variable | Used by | Notes |
|---|---|---|
| `PE_SUPERUSER_PASSWORD` | db (the `pe` superuser) | Only for the container's own setup and emergency access. |
| `PE_OWNER_DB_PASSWORD` | db init, API migrations | Role `pe_owner`. Runs migrations; owns the schema. |
| `PE_APP_DB_PASSWORD` | db init, API | Role `pe_app`. The request path. Bound by row-level security. |
| `ADMIN_TOKEN` | API | Creates tenants and keys. Rotate after any use outside a secure shell. |

## Rules

1. Generate each value with a CSPRNG, at least 32 bytes: `openssl rand -base64 32`.
2. Keep them in an env file readable only by the deploy user, for example `/etc/pe/prod.env` with mode `0600`.
   Pass it with `--env-file`. Do not put values in `docker-compose.prod.yml`, in shell history, or in CI logs.
3. `DATABASE_URL` must use `pe_app`. Never point the API at the superuser: that bypasses tenant isolation.
4. Set the database passwords before the first start. The init script runs once, on an empty volume.
   To change a role password later, run `ALTER ROLE` as `pe` and update the env file, then restart the API.
5. Rotate `ADMIN_TOKEN` and the database passwords on a schedule, and whenever someone with access leaves.

## Not covered here

Keeping these values in a secrets manager (Vault, a cloud KMS) is the next step. Inject them into the env file
at deploy time; the compose file does not change.
