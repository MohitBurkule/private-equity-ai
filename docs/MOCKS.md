# Mock services for firm-internal systems

Firm systems (mail, data rooms, CRMs, drives, SSO) are not reachable from dev or CI. Each one gets an
open-source mock, run the same way as Mailpit: a docker-compose service, a CI service in `api-postgres`,
and an e2e test that skips when the service is not running.

| System | Mock | Status | Wiring |
|---|---|---|---|
| Dev mail (SMTP, API) | Mailpit v1.21.8 | wired | compose `mailpit`, CI, `tests/test_mailpit_e2e.py`, `tests/test_mailpit_ingest.py` |
| Generic IMAP mailbox | GreenMail 2.1.2 | wired | compose `greenmail`, CI, `tests/test_greenmail_e2e.py` |
| Microsoft Graph (Outlook, SharePoint) | WireMock with recorded stubs | planned | contract tests on a fake today: `tests/test_graph_contract.py` |
| Google Drive / Sheets | WireMock or fake-gcs-server | planned | fake today: `tests/test_gdrive_folder.py`, `tests/test_gsheets.py` |
| CRM (Salesforce, HubSpot, DealCloud) | WireMock from OpenAPI, or Prism | planned | fakes today: `tests/test_dealcloud_contract.py`, `tests/test_connectors.py` |
| Object store / doc store | MinIO | planned | not used by an adapter yet |
| SSO | Keycloak or mock-oauth2-server | planned | OAuth tests use a fake token endpoint today |
| SFTP data room | atmoz/sftp | planned | no SFTP adapter yet |
| Slack / Teams | Slack-compatible mock | planned | Slack adapter tested on a fake today |

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
