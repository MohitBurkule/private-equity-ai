//! Optional Rust port of apps/api (FastAPI). Routes ported so far: /health, /me (auth probe), GET/POST /facts.
//! Schema is owned by the alembic migrations in apps/api; this service never runs migrations.

mod alerts;
mod audit;
mod auth;
mod checklist;
mod citations;
mod dd;
mod deals;
mod documents;
mod error;
mod facts;
mod memo;
mod names;
mod notes;
mod peer_sets;
mod proxy;
mod ratelimit;
mod scope;
mod snapshot;
mod visibility;

use axum::{extract::State, http::HeaderMap, routing::get, Json, Router};
use serde_json::{json, Value};
use sqlx::PgPool;
use std::sync::Arc;

#[derive(Clone)]
pub struct AppState {
    pub pool: PgPool,
    /// FastAPI base URL for routes not ported here. None means unported routes return 404.
    pub upstream: Option<String>,
    pub http: reqwest::Client,
    pub limiter: Arc<ratelimit::RateLimiter>,
}

async fn health() -> Json<Value> {
    Json(json!({ "status": "ok" }))
}

/// Auth probe used by the benchmark and parity tests: the caller's tenant and role, nothing secret.
async fn whoami(
    State(s): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Value>, error::ApiError> {
    let (p, tx) = auth::principal(&s, &headers).await?;
    tx.rollback().await.ok();
    Ok(Json(json!({ "tenant": p.tenant, "role": p.role })))
}

pub fn app(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/me", get(whoami))
        .route("/facts", get(facts::list_facts).post(facts::create_fact))
        .route("/documents", get(documents::list_documents))
        .route("/deals", get(deals::list_deals))
        .route("/dd/requests", get(dd::list_requests))
        .route("/dd/questions", get(dd::list_questions))
        .route("/dd/summary", get(dd::dd_summary))
        .route("/alerts", get(alerts::list_alerts))
        .route("/alerts/brief", get(alerts::alerts_brief))
        .route("/deals/:name/checklist", get(checklist::list_checklist))
        .route("/deals/:name/snapshot", get(snapshot::deal_snapshot))
        .route("/deals/:name/notes", get(notes::list_deal_notes))
        .route("/deals/:name/peer-sets", get(peer_sets::list_peer_sets))
        .route("/targets/:tid/notes", get(notes::list_target_notes))
        .route("/memo/templates", get(memo::list_templates))
        .route("/memo/versions", get(memo::list_versions))
        .route("/documents/:doc_id/pages/:number", get(documents::get_page))
        .fallback(proxy::forward)
        .method_not_allowed_fallback(proxy::forward)
        .with_state(state)
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let url = std::env::var("DATABASE_URL")?;
    let pool = PgPool::connect(&url).await?;
    let upstream = std::env::var("FASTAPI_UPSTREAM")
        .ok()
        .filter(|u| !u.is_empty());
    let addr = std::env::var("RS_BIND").unwrap_or_else(|_| "0.0.0.0:8001".into());
    let listener = tokio::net::TcpListener::bind(&addr).await?;
    let http = reqwest::Client::new();
    let per_minute = std::env::var("RATE_LIMIT_PER_MIN")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(600);
    let limiter = Arc::new(ratelimit::RateLimiter::new(per_minute));
    axum::serve(
        listener,
        app(AppState {
            pool,
            upstream,
            http,
            limiter,
        }),
    )
    .await?;
    Ok(())
}
