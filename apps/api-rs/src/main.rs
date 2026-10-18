//! Optional Rust port of apps/api (FastAPI). Routes ported so far: /health, /me (auth probe), GET/POST /facts.
//! Schema is owned by the alembic migrations in apps/api; this service never runs migrations.

mod admin;
mod agent;
mod alerts;
mod audit;
mod auth;
mod calc;
mod checklist;
mod citations;
mod comps;
mod comps_calc;
mod dd;
mod deals;
mod derived;
mod documents;
mod error;
mod facts;
mod fund;
mod fx;
mod legal;
mod memo;
mod memo_text;
mod names;
mod notes;
mod peer_sets;
mod proxy;
mod ratelimit;
mod scope;
mod shareledger;
mod snapshot;
mod sumcheck;
mod tieout;
mod visibility;
mod waterfall;
mod workflows;

use axum::{
    extract::State,
    http::HeaderMap,
    routing::{delete, get, post, put},
    Json, Router,
};
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
        .route("/audit", get(audit::list_audit))
        .route("/audit/verify", get(audit::verify_audit))
        .route("/calc/periods", get(calc::calc_periods))
        .route("/calc/ltm", get(calc::calc_ltm))
        .route("/calc/net-debt", get(calc::calc_net_debt))
        .route("/calc/nwc", get(calc::calc_nwc))
        .route("/calc/nwc-peg", get(calc::calc_nwc_peg))
        .route("/calc/sumcheck", post(sumcheck::calc_sumcheck))
        .route("/calc/tieout", post(tieout::calc_tieout))
        .route("/calc/fund-metrics", post(fund::calc_fund_metrics))
        .route("/calc/waterfall", post(waterfall::calc_waterfall))
        .route("/calc/share-ledger", post(shareledger::calc_share_ledger))
        .route("/calc/comps", post(comps_calc::calc_comps))
        .route("/calc/normalized-ebitda", get(calc::calc_normalized_ebitda))
        .route("/calc/revenue-trend", get(calc::calc_revenue_trend))
        .route("/calc/net-debt-adjusted", get(calc::calc_net_debt_adjusted))
        .route("/admin/keys/:kid", delete(admin::revoke_key))
        .route("/admin/tenants", post(admin::create_tenant))
        .route(
            "/admin/tenants/:tenant_id/keys/:kid/groups/sync",
            post(admin::sync_key_groups),
        )
        .route(
            "/admin/tenants/:tenant_id/keys",
            get(admin::list_keys).post(admin::add_key),
        )
        .route(
            "/admin/tenants/:tenant_id/pii-redaction",
            put(admin::set_pii_redaction),
        )
        .route(
            "/admin/tenants/:tenant_id/document-access",
            get(admin::document_access),
        )
        .route("/agent/runs", get(agent::list_runs))
        .route("/alerts", get(alerts::list_alerts))
        .route("/alerts/brief", get(alerts::alerts_brief))
        .route("/deals/:name/checklist", get(checklist::list_checklist))
        .route("/deals/:name/snapshot", get(snapshot::deal_snapshot))
        .route("/deals/:name/notes", get(notes::list_deal_notes))
        .route("/deals/:name/peer-sets", get(peer_sets::list_peer_sets))
        .route("/targets/:tid/notes", get(notes::list_target_notes))
        .route("/facts/derived", get(derived::fact_derived))
        .route("/memo", get(memo_text::get_memo))
        .route("/workflows", get(workflows::list_workflows))
        .route("/workflows/:wid/last", get(workflows::workflow_last))
        .route("/memo/sections", get(memo_text::get_memo_sections))
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
    // GRAPH_CA_FILE trusts an extra CA, honoured only under PE_TEST_MODE=1 (tests use a local Graph with its own certificate).
    let mut builder = reqwest::Client::builder();
    if std::env::var("PE_TEST_MODE").ok().as_deref() == Some("1") {
        if let Ok(path) = std::env::var("GRAPH_CA_FILE") {
            let pem = std::fs::read(&path)?;
            builder = builder.add_root_certificate(reqwest::Certificate::from_pem(&pem)?);
        }
    }
    if let Some(base) = admin::graph_override() {
        eprintln!("warning: GRAPH_BASE_URL override active under PE_TEST_MODE=1: {base}");
    }
    let http = builder.build()?;
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
