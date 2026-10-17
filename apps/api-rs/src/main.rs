//! Optional Rust port of apps/api (FastAPI). Routes ported so far: /health, /me (auth probe), GET/POST /facts.
//! Schema is owned by the alembic migrations in apps/api; this service never runs migrations.

mod audit;
mod auth;
mod citations;
mod error;
mod facts;

use axum::{extract::State, http::HeaderMap, routing::get, Json, Router};
use serde_json::{json, Value};
use sqlx::PgPool;

#[derive(Clone)]
pub struct AppState {
    pub pool: PgPool,
}

async fn health() -> Json<Value> {
    Json(json!({ "status": "ok" }))
}

/// Auth probe used by the benchmark and parity tests: the caller's tenant and role, nothing secret.
async fn whoami(
    State(s): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Value>, error::ApiError> {
    let (p, tx) = auth::principal(&s.pool, &headers).await?;
    tx.rollback().await.ok();
    Ok(Json(json!({ "tenant": p.tenant, "role": p.role })))
}

pub fn app(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/me", get(whoami))
        .route("/facts", get(facts::list_facts).post(facts::create_fact))
        .with_state(state)
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let url = std::env::var("DATABASE_URL")?;
    let pool = PgPool::connect(&url).await?;
    let addr = std::env::var("RS_BIND").unwrap_or_else(|_| "0.0.0.0:8001".into());
    let listener = tokio::net::TcpListener::bind(&addr).await?;
    axum::serve(listener, app(AppState { pool })).await?;
    Ok(())
}
