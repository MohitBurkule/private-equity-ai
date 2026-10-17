# SSO and roles (GAPS #1, part 1)

## Decisions
- **Identity:** OIDC bearer JWTs from the firm's provider, RS256 only. Set `OIDC_ISSUER`, `OIDC_AUDIENCE` (default `pe-platform`) and either `OIDC_JWKS_URL` (rotating keys) or `OIDC_PUBLIC_KEY_PEM` (pinned key, offline/test). With no issuer set, JWTs are ignored.
- **Tenant:** the token must carry a `tenant` claim naming a tenant that already exists here. The token never creates one.
- **Roles:** an explicit `role` claim wins; a value outside the known roles reads as `viewer`. With no `role` claim, the `groups` claim maps through `GROUP_ROLES` in `app/oidc.py`: `pe-ic-members` → `partner`, `pe-deal-team` → `associate`, highest rank wins, no mapped group → `viewer`.
- **Deal scope:** an optional `deals` claim list limits visibility the same way a key's deal scope does.
- **API keys:** unchanged. A token with two dots is treated as a JWT; anything else as a key.

## Keycloak mock
- `tests/test_keycloak_sso.py` runs against the synthetic realm when `KEYCLOAK_URL` is set. Its tokens come from Keycloak's password grant (dev only, the realm allows it), and the app checks them against the realm JWKS.
- Realm mappers add `tenant` (fixed to `firm-synthetic`), `aud` = `pe-platform` and `groups`.

## Not done
- Per-role permissions for IR and compliance beyond what `app/acl.py` already grants.
