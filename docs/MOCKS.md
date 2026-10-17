# Mock services for firm-internal systems

Firm systems (mail, data rooms, CRMs, drives, SSO) are not reachable from dev or CI. Each one gets an
open-source mock, run the same way as Mailpit: a docker-compose service, a CI service in `api-postgres`,
and an e2e test that skips when the service is not running.

| System | Mock | Status | Wiring |
|---|---|---|---|
| Dev mail (SMTP, API) | Mailpit v1.21.8 | wired | compose `mailpit`, CI, `tests/test_mailpit_e2e.py`, `tests/test_mailpit_ingest.py` |
| Generic IMAP mailbox | GreenMail 2.1.2 | wired | compose `greenmail`, CI, `tests/test_greenmail_e2e.py` |
| Microsoft Graph (Outlook, SharePoint) | WireMock 3.9.1 (jar or compose) | wired | compose `wiremock` (port 8089), `tests/test_wiremock_adapters.py`, `tests/test_sharepoint_wiremock.py` (library to documents), `tests/test_outlook_sync_flow.py` (mail to DD document), skips without `WIREMOCK_JAR` or `WIREMOCK_URL` |
| Google Drive | WireMock 3.9.1 (jar or compose) | wired | `tests/test_wiremock_adapters.py` |
| CRM (Salesforce SOQL, HubSpot companies/deals/contacts) | WireMock 3.9.1 (jar or compose) | wired | `tests/test_wiremock_adapters.py` |
| Slack (conversations.list, conversations.history, incoming webhooks) | WireMock 3.9.1 (jar) | wired locally | `tests/test_wiremock_adapters.py`, poster in `app/chat_alerts.py`, endpoint flow in `tests/test_chat_delivery_e2e.py` |
| Teams (incoming webhook) | WireMock 3.9.1 (jar) | wired locally | `tests/test_wiremock_adapters.py`, endpoint flow in `tests/test_chat_delivery_e2e.py` |
| SSO / OIDC | mock-oauth2-server 6.1.1 (jar) | wired | `tests/test_oauth_mock_idp_e2e.py`, `tests/test_sso_mock_idp_e2e.py` (roles from scope, config in `apps/api/tests/mock_oauth/config.json`); both skip without `MOCK_OAUTH_URL` |
| Object store (S3) | moto (in-process server) | wired | `apps/api/app/connectors/s3.py`, `tests/test_s3_moto.py` |
| SFTP data room | Apache MINA SSHD (jar, `tests/mocks/sftp/SftpMock.java`) | wired | `apps/api/app/connectors/sftp.py`, `tests/test_sftp_mina.py`, needs `SSHD_CLASSPATH` |
| Portfolio-company ledger (trial balance → monthly revenue, net income) | SYNTHETIC ledger API, WireMock 3.9.1 (jar) | wired | `apps/api/app/connectors/accounting.py`, `app/accounting.py`, `tests/test_accounting_flow.py`, `tests/test_accounting_wiremock.py` |
| Carta cap table (holdings → cited shares and ownership per holder) | SYNTHETIC cap-table API, WireMock 3.9.1 (jar) | wired | `apps/api/app/connectors/carta.py`, `app/captable.py`, `tests/test_carta_flow.py`, `tests/test_carta_wiremock.py` |
| Google Sheets | WireMock 3.9.1 (jar) | wired | `tests/test_gsheets_wiremock.py` (pull through sync, push); `tests/test_gsheets.py` keeps an in-test fake so the flow runs without a jar |
| Keycloak | not used | skipped | mock-oauth2-server covers OIDC |
| MinIO | not used | blocked | binary download returned 410 in the build sandbox; S3 tests use moto |

The jar mocks are fetched in CI by `apps/api/tests/mocks/pom.xml` (Maven, Java 21) in the `api-postgres` job, which sets `WIREMOCK_JAR`, `SSHD_CLASSPATH` and `MOCK_OAUTH_URL`. Each test skips cleanly without its env var.

### mock-oauth2-server token recipe (for SSO roles)

Run with `config.json`, which turns off interactive login and adds claims per token:

```json
{"interactiveLogin": false, "tokenCallbacks": [{"issuerId": "default", "tokenExpiry": 3600,
  "requestMappings": [{"requestParam": "scope", "match": "*",
    "claims": {"sub": "ic@firm.test", "aud": ["cid"], "groups": ["pe-ic-members"]}}]}]}
```

Start: `JSON_CONFIG_PATH=config.json java -cp <classpath> no.nav.security.mock.oauth2.StandaloneMockOAuth2ServerKt`
(the classpath comes from Maven: artifact `no.nav.security:mock-oauth2-server:6.1.1`). Discovery: `http://localhost:8080/default/.well-known/openid-configuration`.
The authorize request needs `scope=openid` (plus `offline_access` for a refresh token). Do not send `prompt=consent` to the mock: it shows a login page.

## Running the wired mocks

```
docker compose up -d mailpit greenmail
GREENMAIL_IMAP_PORT=3143 GREENMAIL_SMTP_PORT=3025 MAILPIT_API_URL=http://localhost:8025 \
  SMTP_HOST=localhost SMTP_PORT=1025 pytest apps/api/tests/test_greenmail_e2e.py apps/api/tests/test_mailpit_e2e.py
```

WireMock runs as a compose service too; the adapter tests then use it instead of starting a jar:

```
docker compose up -d wiremock
WIREMOCK_URL=http://localhost:8089 pytest apps/api/tests/test_wiremock_adapters.py
```

Tests reset the server's stubs at the start of each module when `WIREMOCK_URL` is set. Do not point it at a shared server.

Without Docker, GreenMail runs from its standalone jar (Maven: `com.icegreen:greenmail-standalone`):

```
java -Dgreenmail.setup.test.imap -Dgreenmail.setup.test.smtp -Dgreenmail.hostname=127.0.0.1 \
     -Dgreenmail.port.imap=3143 -Dgreenmail.port.smtp=3025 -Dgreenmail.users=ic@firm.test:app-pass \
     -jar greenmail-standalone.jar
```

Mock credentials are fixed test values. They must never be used for a real account.

## Synthetic firm-system mocks (`make demo-mocks`)

All SYNTHETIC: response shapes are invented for tests, not copied from any vendor's API.

| System | Mock | Where | Flow today |
|---|---|---|---|
| DealCloud (companies, deals) | WireMock stubs | `deploy/mocks/wiremock/mappings/dealcloud.json` | stub smoke test only; no connector |
| iManage (folder documents) | WireMock stubs | `deploy/mocks/wiremock/mappings/imanage.json` | stub smoke test only; no connector |
| Datasite (room files) | WireMock stubs | `deploy/mocks/wiremock/mappings/datasite.json` | stub smoke test only; no connector |
| Fund admin (capital calls, NAV) | WireMock stubs | `deploy/mocks/wiremock/mappings/fund-admin.json` | stub smoke test only; no connector |
| SSO roles | Keycloak 26.0.7, realm `firm-synthetic` | compose `keycloak` on 8081 | not yet tested against the app |
| Fund-admin file drop | atmoz/sftp | compose `sftp` on 2222 (user `fundadmin`) | connector covered by `tests/test_sftp_mina.py` with MINA, not against this image |

`make demo-mocks` starts the WireMock, Keycloak and SFTP services and runs `tests/test_firm_mocks_smoke.py` and `tests/test_wiremock_adapters.py`. The stub smoke test uses an in-process WireMock jar when `WIREMOCK_JAR` is set, or the compose service when `WIREMOCK_URL` is set.
