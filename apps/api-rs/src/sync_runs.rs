//! Port of GET /sync-runs (app/main.py list_sync_runs). Restricted keys see only runs on deals in their scope.
//! Single-run detail and syncing stay on FastAPI.

use crate::auth::principal;
use crate::error::ApiError;
use crate::AppState;
use axum::{
    extract::{Query, State},
    http::HeaderMap,
    Json,
};
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize)]
pub struct RunQuery {
    limit: Option<i64>,
}

/// sync_run row: id, connector, connection_id, deal, started_at, finished_at, status, ingested, unchanged,
/// skipped, error.
type RunRow = (
    i32,
    String,
    Option<i32>,
    Option<String>,
    String,
    Option<String>,
    String,
    i32,
    i32,
    i32,
    Option<String>,
);

pub async fn list_sync_runs(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<RunQuery>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    // Restricted keys: runs whose deal is in their scope. Unscoped keys: every run.
    let scope: Option<Vec<String>> = p.deals.as_ref().map(|d| d.iter().cloned().collect());
    // Python: max(1, min(limit, 200)), default 25.
    let limit = q.limit.unwrap_or(25).clamp(1, 200);
    let rows: Vec<RunRow> = sqlx::query_as(
        "SELECT id, connector, connection_id, deal, started_at, finished_at, status, ingested, unchanged, \
         skipped, error FROM sync_run WHERE ($1::text[] IS NULL OR deal = ANY($1)) \
         ORDER BY id DESC LIMIT $2",
    )
    .bind(scope)
    .bind(limit)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    // Python _run_dict.
    let out: Vec<Value> = rows
        .into_iter()
        .map(|(id, connector, connection_id, deal, started_at, finished_at, status, ingested, unchanged, skipped, error)| {
            json!({
                "id": id, "connector": connector, "connection_id": connection_id, "deal": deal,
                "started_at": started_at, "finished_at": finished_at, "status": status,
                "ingested": ingested, "unchanged": unchanged, "skipped": skipped, "error": error,
            })
        })
        .collect();
    Ok(Json(Value::Array(out)))
}
