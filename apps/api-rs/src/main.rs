//! Optional Rust port of apps/api (FastAPI). Slice 1: health + API-key auth + tenant binding.
//! Schema is owned by the alembic migrations in apps/api; this service never runs migrations.

use axum::{extract::State, http::{HeaderMap, StatusCode}, routing::get, Json, Router};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use sqlx::{PgPool, Postgres, Transaction};

#[derive(Clone)]
pub struct AppState {
    pub pool: PgPool,
}

#[derive(Debug)]
struct Principal {
    tenant: String,
    role: String,
}

/// Matches FastAPI: sha256 of the presented key, looked up in api_key; revoked keys fail.
fn hash_key(key: &str) -> String {
    hex::encode(Sha256::digest(key.as_bytes()))
}

async fn principal(pool: &PgPool, headers: &HeaderMap) -> Result<(Principal, Transaction<'static, Postgres>), StatusCode> {
    let raw = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .ok_or(StatusCode::UNAUTHORIZED)?;
    let token = raw
        .get(..7)
        .filter(|p| p.eq_ignore_ascii_case("bearer "))
        .map(|_| raw[7..].trim())
        .ok_or(StatusCode::UNAUTHORIZED)?;
    // JWTs (two dots) go to OIDC in FastAPI; not ported yet.
    if token.matches('.').count() == 2 {
        return Err(StatusCode::NOT_IMPLEMENTED);
    }
    let mut tx = pool.begin().await.map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    let row: Option<(String, String, bool)> =
        sqlx::query_as("SELECT tenant_id, role, revoked FROM api_key WHERE key_hash = $1")
            .bind(hash_key(token))
            .fetch_optional(&mut *tx)
            .await
            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    match row {
        Some((tenant, role, false)) => {
            // Tenant comes only from the key. Transaction-local, so pooled connections cannot leak it.
            sqlx::query("SELECT set_config('app.tenant_id', $1, true)")
                .bind(&tenant)
                .execute(&mut *tx)
                .await
                .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
            Ok((Principal { tenant, role }, tx))
        }
        _ => Err(StatusCode::UNAUTHORIZED),
    }
}

async fn health() -> Json<Value> {
    Json(json!({ "status": "ok" }))
}

/// Auth probe used by the parity tests: returns the caller's tenant and role, nothing secret.
async fn whoami(State(s): State<AppState>, headers: HeaderMap) -> Result<Json<Value>, StatusCode> {
    let (p, tx) = principal(&s.pool, &headers).await?;
    tx.rollback().await.ok();
    Ok(Json(json!({ "tenant": p.tenant, "role": p.role })))
}

pub fn app(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/me", get(whoami))
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
