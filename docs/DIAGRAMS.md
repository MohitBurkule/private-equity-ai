# System diagrams

Mermaid, rendered by GitHub. The database diagram is generated from the models (`scripts/gen_er.py`), so it
cannot drift; the rest are drawn by hand from `docker-compose.yml`, `.github/workflows/ci.yml` and `apps/api/app`.

## 1. Database (generated)

Foreign keys drawn here are the ones declared in the schema. Every tenant-owned table also carries a
`tenant_id` column that is not a declared key: isolation is enforced by Postgres row-level security
(`FORCE RLS`, `app.tenant_id` set per transaction), not by joins. Tables on that list are in `app/rls.py`.

<!-- er:start -->
```mermaid
erDiagram
  api_key {
    VARCHAR key_hash PK
    VARCHAR tenant_id FK
    BOOLEAN revoked
    VARCHAR role
    TEXT deals
  }
  dd_request {
    INTEGER id PK
    VARCHAR tenant_id
    VARCHAR deal
    VARCHAR category
    VARCHAR title
    VARCHAR status
    VARCHAR document_id FK
    TEXT note
    VARCHAR updated_at
  }
  deal {
    INTEGER id PK
    VARCHAR tenant_id
    VARCHAR name
    VARCHAR stage
    TEXT note
    VARCHAR updated_at
  }
  document {
    VARCHAR id PK
    VARCHAR tenant_id
    VARCHAR sha256
    VARCHAR filename
    INTEGER n_pages
    VARCHAR kind
    VARCHAR deal
  }
  eval_run {
    INTEGER id PK
    VARCHAR tenant_id
    VARCHAR suite
    TEXT metrics
    TEXT note
    VARCHAR ran_at
    VARCHAR recorded_by
  }
  fact {
    INTEGER id PK
    VARCHAR tenant_id
    VARCHAR entity
    VARCHAR metric
    VARCHAR period
    NUMERIC value
    VARCHAR unit
    VARCHAR basis
    VARCHAR status
    VARCHAR reviewed_by
    VARCHAR reviewed_at
    TEXT review_note
  }
  fact_source {
    INTEGER id PK
    INTEGER fact_id FK
    VARCHAR document_id FK
    INTEGER page
    TEXT quote
  }
  holding {
    INTEGER id PK
    VARCHAR tenant_id
    VARCHAR platform
    VARCHAR company
    NUMERIC shares
    NUMERIC price
    VARCHAR currency
    VARCHAR acquired
    VARCHAR document_id FK
    INTEGER line
  }
  ingest_job {
    VARCHAR id PK
    VARCHAR tenant_id
    VARCHAR filename
    VARCHAR deal
    VARCHAR role
    TEXT scope
    VARCHAR key_id
    VARCHAR status
    INTEGER attempts
    VARCHAR stage
    TEXT error
    TEXT result
    VARCHAR spool_path
    VARCHAR created_at
    VARCHAR updated_at
  }
  page {
    INTEGER id PK
    VARCHAR document_id FK
    INTEGER number
    TEXT text
    VARCHAR label
    VARCHAR method
    DOUBLE ocr_confidence
  }
  tenant {
    VARCHAR id PK
    VARCHAR name
  }
  tenant ||--o{ api_key : "tenant_id"
  document ||--o{ dd_request : "document_id"
  document ||--o{ fact_source : "document_id"
  fact ||--o{ fact_source : "fact_id"
  document ||--o{ holding : "document_id"
  document ||--o{ page : "document_id"
```
<!-- er:end -->

## 2. Architecture (components)

```mermaid
flowchart LR
  subgraph Client
    UI[React + TypeScript UI<br/>Workspace, Review, Deals, Portfolio, Evals]
    CLI[scripts: smoke, seed_demo, backup]
  end
  subgraph API[FastAPI service]
    MW[Middleware<br/>request id, access log, metrics, rate limit]
    AUTH[Auth<br/>API key sha256 -> Principal tenant, role, deal wall]
    ING[Ingest<br/>PDF, OCR, XLSX, iXBRL, SH01]
    FACT[Facts<br/>span-verified citations, review queue]
    RAG[Search + Ask<br/>BM25 retrieval, verification gate, abstention]
    CALC[Pure calculators<br/>LTM, net debt, tie-out, ledger, fund metrics, waterfall]
    OUT[Outputs<br/>memo md/docx/pptx, DDQ, portfolio report]
    FEEDS[Feeds<br/>SEC, Companies House, quotes, holdings CSV]
    AUD[Audit chain]
  end
  DB[(PostgreSQL 16 + RLS)]
  RD[(Redis<br/>rate limit, jobs)]
  SP[(Spool volume<br/>uploaded files)]
  LLM[[LLM provider<br/>Anthropic adapter]]
  EXT[[SEC EDGAR, Companies House,<br/>FactSet, Yahoo, Stooq]]
  UI --> MW
  CLI --> MW
  MW --> AUTH --> ING & FACT & RAG & CALC & OUT & FEEDS
  ING --> SP
  ING & FACT & RAG & OUT & FEEDS & AUD --> DB
  MW --> RD
  RAG --> LLM
  FEEDS --> EXT
  FACT -. every figure links to page and quote .-> OUT
```

## 3. Trust path: document to cited answer

```mermaid
sequenceDiagram
  participant U as User
  participant A as API
  participant D as Postgres
  participant L as LLM
  U->>A: upload document
  A->>D: store pages (text or OCR, OCR flagged)
  U->>A: POST /facts (value, page, quote)
  A->>A: quote on that page? number matches quote?
  A->>D: fact verified, or 422 refused
  U->>A: POST /ask
  A->>D: retrieve pages (tenant + deal wall)
  A->>L: question + pages
  L-->>A: draft answer with citations
  A->>A: gate: every claim backed by a verbatim span
  A-->>U: answer with sources, or abstain
```

## 4. Deployment (docker compose)

```mermaid
flowchart TB
  user([Browser]) -->|:8080| web
  subgraph host[Docker host]
    web[web: nginx + built React app]
    api[api: uvicorn FastAPI :8000]
    db[(db: pgvector/pg16<br/>roles pe_owner migrate, pe_app runtime)]
    redis[(redis:7)]
    pgdata[[volume pgdata]]
    spool[[volume spool]]
    web -->|/api proxy| api
    api -->|DATABASE_URL pe_app, RLS applies| db
    api -->|MIGRATE_DATABASE_URL pe_owner, startup only| db
    api --> redis
    api --- spool
    db --- pgdata
  end
  api -.->|HTTPS, optional keys| ext[[LLM, SEC, Companies House, FactSet, Yahoo]]
  prom[Prometheus] -.->|/metrics + admin token| api
  backup[scripts/backup.sh] -.-> db
```

## 5. CI and release

```mermaid
flowchart LR
  push[push / PR] --> lint[ruff]
  lint --> api[api tests on SQLite]
  lint --> pg[api-postgres: RLS as non-owner role<br/>+ live-server smoke]
  push --> web[web: typecheck + build]
  api & pg & web --> merge{all green} --> main[merge to main]
```
