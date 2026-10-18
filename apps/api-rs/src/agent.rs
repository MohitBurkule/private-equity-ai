//! Port of GET /agent/runs (app/main.py agent_runs, app/agent.py run_dict): the tenant's most recent workflow and
//! agent runs, newest first. The run and tool registry and the runners stay on FastAPI; this is a read of the table.

use crate::auth::principal;
use crate::error::ApiError;
use crate::AppState;
use axum::{
    extract::{Query, State},
    http::HeaderMap,
    Json,
};
use serde_json::{json, Value};
use std::collections::HashMap;

type RunRow = (
    i32,
    String,
    String,
    Option<String>,
    String,
    String,
    Option<String>,
    Option<String>,
    String,
);

/// FastAPI's `limit: int = 20`, with no bounds: the value is clamped to 1..100 after parsing.
fn runs_limit(raw: Option<&String>) -> Result<i64, ApiError> {
    let Some(raw) = raw else { return Ok(20) };
    let n: i64 = raw.parse().map_err(|_| ApiError::query_int("limit", raw))?;
    Ok(n.clamp(1, 100))
}

/// Python run_dict: `steps` and `result` are stored as JSON text; an empty result reads back as null.
fn run_json(r: RunRow) -> Value {
    let (id, kind, name, goal, status, steps, result, error, created_at) = r;
    json!({
        "id": id,
        "kind": kind,
        "name": name,
        "goal": goal,
        "status": status,
        "steps": serde_json::from_str::<Value>(&steps).unwrap_or(Value::Null),
        "result": result.filter(|r| !r.is_empty()).map(|r| serde_json::from_str::<Value>(&r).unwrap_or(Value::Null)),
        "error": error,
        "created_at": created_at,
    })
}

pub async fn list_runs(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, ApiError> {
    let (_p, mut tx) = principal(&s, &headers).await?;
    let limit = runs_limit(q.get("limit"))?;
    let rows: Vec<RunRow> = sqlx::query_as(
        "SELECT id, kind, name, goal, status, steps, result, error, created_at FROM agent_run \
         ORDER BY id DESC LIMIT $1",
    )
    .bind(limit)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    Ok(Json(Value::Array(rows.into_iter().map(run_json).collect())))
}
