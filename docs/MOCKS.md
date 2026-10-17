# Mock services for firm-internal systems

Firm systems (mail, data rooms, CRMs, drives, SSO) are not reachable from dev or CI. Each one gets an
open-source mock, run the same way as Mailpit: a docker-compose service, a CI service in `api-postgres`,
and an e2e test that skips when the service is not running.

| System | Mock | Status | Wiring |
|---|---|---|---|
| Dev mail (SMTP, API) | Mailpit v1.21.8 | wired | compose `mailpit`, CI, `tests/test_mailpit_e2e.py`, `tests/test_mailpit_ingest.py` |
| Generic IMAP mailbox | GreenMail 2.1.2 | wired | compose `greenmail`, CI, `tests/test_greenmail_e2e.py` |
| Microsoft Graph (Outlook, SharePoint) | WireMock 3.9.1 (jar) | wired locally | `tests/test_wiremock_adapters.py`, skips without `WIREMOCK_JAR` |
| Google Drive | WireMock 3.9.1 (jar) | wired locally | `tests/test_wiremock_adapters.py` |
| CRM (Salesforce SOQL, HubSpot companies/deals/contacts) | WireMock 3.9.1 (jar) | wired locally | `tests/test_wiremock_adapters.py` |
| Slack (conversations.list, conversations.history) | WireMock 3.9.1 (jar) | wired locally | `tests/test_wiremock_adapters.py` |
| SSO / OIDC | mock-oauth2-server 6.1.1 (jar) | wired locally | `tests/test_oauth_mock_idp_e2e.py`, skips without `MOCK_OAUTH_URL` |
| Object store (S3) | moto server (pip) | available, no adapter yet | no S3 connector exists |
| SFTP data room | Apache MINA SSHD (jar) | not wired | no SFTP connector exists |
| Google Sheets | fake in tests | planned mock | `tests/test_gsheets.py` (in-test fake) |
| Keycloak | not used | skipped | mock-oauth2-server covers OIDC |
| MinIO | not used | blocked | binary download returned 410 in the build sandbox |

The jar-based mocks are not in CI yet: CI needs Java and a download step. Each test skips cleanly without its env var.

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

Without Docker, GreenMail runs from its standalone jar (Maven: `com.icegreen:greenmail-standalone`):

```
java -Dgreenmail.setup.test.imap -Dgreenmail.setup.test.smtp -Dgreenmail.hostname=127.0.0.1 \
     -Dgreenmail.port.imap=3143 -Dgreenmail.port.smtp=3025 -Dgreenmail.users=ic@firm.test:app-pass \
     -jar greenmail-standalone.jar
```

Mock credentials are fixed test values. They must never be used for a real account.
