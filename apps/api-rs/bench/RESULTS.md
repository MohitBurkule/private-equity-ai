# Rust vs FastAPI, matched run (rate limits high on both)

Setup: one box, oha 50 connections, 10 s per route. FastAPI 4 uvicorn workers (uvloop, httptools), `RATE_LIMIT_PER_MIN=1000000`. Rust 4 Tokio threads, `RATE_LIMIT_PER_MIN=1000000`. Same Postgres and tenant key. Load generator shares the box, so compare stacks, not absolute numbers.

| route | FastAPI RPS | Rust RPS | FastAPI p50 / p99 | Rust p50 / p99 |
|---|---|---|---|---|
| /health | 4,290 | 92,238 | 9.8 / 35.4 ms | 0.43 / 2.1 ms |
| /facts?entity=Bench | 191 | 3,955 | 179 / 863 ms | 11.9 / 24.1 ms |
| /documents | 407 | 5,833 | 118 / 270 ms | 7.5 / 18.3 ms |
| /documents/{id}/pages/3 | 372 | 5,006 | 107 / 413 ms | 8.8 / 21.5 ms |
| /memo/templates | 417 | 7,579 | 115 / 259 ms | 6.1 / 12.9 ms |
| /memo/versions?entity=Bench | 467 | 9,194 | 104 / 212 ms | 4.8 / 11.9 ms |

Memory (PSS summed over process tree, idle after the run): FastAPI 584 MiB (6 processes), Rust 9 MiB (1 process).

Cold start (process launch to first 200 on /health): Rust 18 ms, FastAPI 2,402 ms (4 workers).

Caveats: both stacks now run a limiter (FastAPI at 1,000,000/min, Rust at the same value), so no 429s skew the numbers. Route /health is the framework floor, not a product number.

Re-run: `KEY_FILE=... DOC=<id with page 3> PAGE=3 DUR=10s CONC=50 bash apps/api-rs/bench/run.sh`
