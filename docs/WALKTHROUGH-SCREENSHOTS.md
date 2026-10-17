# Walkthrough: screenshot the mock flows

Synthetic data only. Every system here is a dev mock (see `docs/MOCKS.md`).

## 1. Run the flows
```
make demo-mocks
```
With Docker running, this starts WireMock, Keycloak and SFTP by compose. Without Docker it runs the tests that
start WireMock and MINA from local jars (`WIREMOCK_JAR`, `SSHD_CLASSPATH`). Keycloak needs `KEYCLOAK_URL`.
Expect the pytest summary with no skips, and screenshot the terminal at that point.

## 2. What to capture
| Flow | Where it shows | Capture |
|---|---|---|
| SFTP drop (fund admin) | `apps/api/tests/test_sftp_mina.py` output | pytest pass line |
| Datasite room export | `apps/api/tests/test_datasite_flow.py` | pytest pass line; then `GET /facts` filtered to the deal, showing the cited workbook cell |
| DealCloud stage sync | `apps/api/tests/test_dealcloud_stage_sync.py` | pytest pass line; `stage_conflict` alert in the alerts list |
| Fund-admin workbook | `apps/api/tests/test_fund_admin_flow.py` | KPI values on the company page (`capital_call_usd`, `nav_usd`) |
| Fund-admin API | `apps/api/tests/test_fundadmin_api_flow.py` | the facts listed right after sync, with no second call |
| Keycloak SSO | `apps/api/tests/test_keycloak_sso.py` | pytest pass line; groups `pe-ic-members` and `pe-deal-team` both allowed to edit |

## 3. Admin views to open
- WireMock requests log: `http://localhost:8089/__admin/requests` (lists every mock call a flow made).
- Mailpit: `http://localhost:8025` (mail the app sent; nothing leaves the stack).
- Keycloak admin: `http://localhost:8081`, realm `firm-synthetic`, login `admin` / `admin` (dev only).

## 4. Rules
- Crop out any token or API key in a screenshot.
- Label each image with the flow name above and the commit sha.
