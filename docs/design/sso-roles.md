# SSO and roles (GAPS #1, part 1)

## Decisions
- **Identity:** OIDC bearer JWTs from the firm's provider, RS256 only. Set `OIDC_ISSUER`, `OIDC_AUDIENCE` (default `pe-platform`) and either `OIDC_JWKS_URL` (rotating keys) or `OIDC_PUBLIC_KEY_PEM` (pinned key, offline/test). With no issuer set, JWTs are ignored.
- **Tenant:** the token must carry a `tenant` claim naming a tenant that already exists here. The token never creates one.
- **Roles:** three roles, as now (`admin`, `analyst`, `viewer`). A `role` claim outside those, or none, becomes `viewer`. The GAPS list of associate, VP, partner, IR and compliance is not mapped yet. Mapping would need per-role permissions, which is the next part.
- **Deal scope:** an optional `deals` claim list limits visibility the same way a key's deal scope does.
- **API keys:** unchanged. A token with two dots is treated as a JWT; anything else as a key.

## Not done
- Per-role permissions beyond the three roles (associate, IR, compliance).
- Testing against the Keycloak mock. The mock is listed as planned in `docs/MOCKS.md`; these tests use a locally generated key, so they do not need it.
