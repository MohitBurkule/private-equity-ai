# private-equity-ai

AI platform for private equity: automated due diligence, IC materials, firm-wide search, portfolio tracking. Every insight links to its source document. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Status: M0 scaffold. Private for now, planned open-source.

## Dev
```
docker compose up --build   # api on :8000, postgres, redis
cd apps/api && pip install -e '.[dev]' && pytest
```
