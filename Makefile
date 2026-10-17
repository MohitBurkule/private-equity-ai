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

# Firm-system mocks (all SYNTHETIC): WireMock stubs for DealCloud, iManage, Datasite and fund admin, a Keycloak
# realm for SSO roles, and an SFTP drop for fund-admin files. Starts them, then runs the tests that use each one.
demo-mocks:  ## Start the synthetic firm-system mocks and run their smoke tests (needs Docker)
	docker compose up -d wiremock keycloak sftp
	WIREMOCK_URL=http://localhost:8089 python3 -m pytest -q \
		apps/api/tests/test_firm_mocks_smoke.py apps/api/tests/test_wiremock_adapters.py \
		apps/api/tests/test_sftp_mina.py apps/api/tests/test_datasite_flow.py \
		apps/api/tests/test_dealcloud_stage_sync.py apps/api/tests/test_fund_admin_flow.py \
		apps/api/tests/test_fundadmin_api_flow.py

.PHONY: demo-mocks
