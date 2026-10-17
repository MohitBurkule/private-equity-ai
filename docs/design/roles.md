# Per-role permissions (GAPS #1, part 2)

## Decisions
- **Roles:** `admin`, `partner`, `vp`, `associate`, `compliance`, `ir`, `viewer`. `analyst` stays as the legacy name for `associate`, so existing keys keep working.
- **One table:** `CAPABILITIES` in `app/acl.py` maps each capability to its roles. Endpoints ask `require(capability)`, never a role name.
- **Capabilities:**
  - `write`: upload, facts, deal stage and notes, checklists. Partner, VP, associate, admin.
  - `govern`: legal hold, MNPI flag, deal delete, retention purges. Partner, VP, compliance, admin.
- **Compliance** can hold and flag deals but cannot edit analysis. It cannot upload either.
- **IR** reads the tenant and writes nothing. LP and fund-level writes are not built yet.
- **Viewer** reads only.
- **MNPI:** an analyst scoped to a deal can no longer unset its MNPI flag. Only `govern` roles can.

## Not done
- IR-specific write scope (LP reporting, fund cash flows).
- Per-deal role overrides. A key still has one role for the whole tenant.
- The mock-oauth2-server e2e test (`tests/test_sso_mock_idp_e2e.py`) is skipped here: no Java or Docker mock is running in this sandbox. Run it with `MOCK_OAUTH_URL` set.
