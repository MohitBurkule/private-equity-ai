//! Port of GET /evals (app/main.py eval_list). Recording a run stays on FastAPI.

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
pub struct EvalQuery {
    suite: Option<String>,
    limit: Option<i64>,
}

/// eval_run row: id, suite, ran_at, note, recorded_by, metrics.
type EvalRow = (i32, String, String, Option<String>, String, String);

pub async fn list_evals(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<EvalQuery>,
) -> Result<Json<Value>, ApiError> {
    let (_p, mut tx) = principal(&s, &headers).await?;
    // Python `if suite:`: an empty filter means no filter. Python clamps limit to 1..500, default 100.
    let suite = q.suite.filter(|s| !s.is_empty());
    let limit = q.limit.unwrap_or(100).clamp(1, 500);
    let rows: Vec<EvalRow> = sqlx::query_as(
        "SELECT id, suite, ran_at, note, recorded_by, metrics FROM eval_run \
         WHERE ($1::text IS NULL OR suite = $1) ORDER BY id DESC LIMIT $2",
    )
    .bind(suite)
    .bind(limit)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    let out: Vec<Value> = rows
        .into_iter()
        .map(|(id, suite, ran_at, note, recorded_by, metrics)| {
            json!({
                "id": id, "suite": suite, "ran_at": ran_at, "note": note, "recorded_by": recorded_by,
                "metrics": serde_json::from_str::<Value>(&metrics).unwrap_or(Value::Null),
            })
        })
        .collect();
    Ok(Json(Value::Array(out)))
}
