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
