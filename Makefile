# Local demo helpers. `make demo` runs everything on SQLite. For Postgres, start the API (docs/RUNBOOK.md), then `make seed-demo`.
API ?= http://localhost:8000
ADMIN_TOKEN ?= adm
DATA ?= data

seed-demo:  ## Seed a fresh tenant with real public filings (needs pdftotext)
	python3 scripts/seed_real_demo.py $(API) $(ADMIN_TOKEN) $(DATA)

.PHONY: seed-demo

demo:  ## API on SQLite plus the built web UI, no Postgres or Docker (see scripts/demo_local.sh)
	bash scripts/demo_local.sh

.PHONY: demo

test-postgres:  ## Full API suite on a throwaway Postgres 18 (embedded-postgres, no Docker; set PG_RUN_AS=<non-root user>)
	bash scripts/test_postgres.sh

.PHONY: test-postgres

ci:  ## Local merge gate (Actions is blocked): ruff, alembic heads, pytest on SQLite and Postgres, web tsc + vitest, Rust fmt/clippy/test
	cd apps/api && python3 -m ruff check . && python3 -m pytest -q tests/test_alembic_heads.py && python3 -m pytest -q
	bash scripts/test_postgres.sh
	cd apps/web && npm ci --no-audit --no-fund && npx tsc --noEmit && npx vitest run
	cd apps/api-rs && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test

.PHONY: ci

# Firm-system mocks (all SYNTHETIC): WireMock stubs for DealCloud, iManage, Datasite and fund admin, a Keycloak
# realm for SSO roles, and an SFTP drop for fund-admin files. Starts them, then runs the tests that use each one.
demo-mocks:  ## Run the firm-system mock flows: compose mocks when Docker runs, else local jars (see docs/MOCKS.md)
	@sh deploy/mocks/tls/make-cert.sh >/dev/null
	@if docker info >/dev/null 2>&1; then \
		docker compose up -d wiremock keycloak sftp && \
		export WIREMOCK_URL=http://localhost:8089 KEYCLOAK_URL=http://localhost:8081 WIREMOCK_HTTPS_URL=https://localhost:8443 WIREMOCK_TLS_KEYSTORE=$$PWD/deploy/mocks/tls/out/keystore.p12; \
	else \
		echo 'no Docker: WireMock and MINA need WIREMOCK_JAR and SSHD_CLASSPATH; Keycloak runs only with KEYCLOAK_URL'; \
	fi; \
	python3 -m pytest -q \
		apps/api/tests/test_firm_mocks_smoke.py apps/api/tests/test_wiremock_adapters.py \
		apps/api/tests/test_sftp_mina.py apps/api/tests/test_datasite_flow.py \
		apps/api/tests/test_dealcloud_stage_sync.py apps/api/tests/test_fund_admin_flow.py \
		apps/api/tests/test_fundadmin_api_flow.py apps/api/tests/test_keycloak_sso.py \
		apps/api/tests/test_outlook_sync_flow.py apps/api/tests/test_chat_delivery_e2e.py \
		apps/api/tests/test_sharepoint_wiremock.py apps/api/tests/test_gsheets_wiremock.py \
		apps/api/tests/test_accounting_flow.py apps/api/tests/test_accounting_wiremock.py \
		apps/api/tests/test_carta_flow.py apps/api/tests/test_carta_wiremock.py \
		apps/api/tests/test_docusign_stage.py apps/api/tests/test_docusign_wiremock.py \
		apps/api/tests/test_docusign_connect.py apps/api/tests/test_monthly_covenant.py \
		apps/api/tests/test_imanage_wiremock.py \
		apps/api/tests/test_netdocuments_flow.py apps/api/tests/test_netdocuments_wiremock.py \
		apps/api/tests/test_permission_sync_wiremock.py

.PHONY: demo-mocks
