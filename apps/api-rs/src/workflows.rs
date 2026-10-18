//! Port of GET /workflows and GET /workflows/{id}/last (app/main.py workflow_list, workflow_last). Create, delete and
//! the scheduler stay on FastAPI and are relayed.

use crate::auth::principal;
use crate::error::ApiError;
use crate::AppState;
use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    Json,
};
use serde_json::{json, Value};

/// workflow_schedule row: id, name, kind, every_days, next_run, last_run, last_status, active.
type ScheduleRow = (
    i32,
    String,
    String,
    i32,
    String,
    Option<String>,
    Option<String>,
    i32,
);

/// workflow_schedule row plus last_result, for the single-workflow read.
type LastRow = (
    i32,
    String,
    String,
    i32,
    String,
    Option<String>,
    Option<String>,
    i32,
    Option<String>,
);

/// Python _wf_out.
fn schedule_json(r: &ScheduleRow) -> Value {
    json!({
        "id": r.0, "name": r.1, "kind": r.2, "every_days": r.3, "next_run": r.4,
        "last_run": r.5, "last_status": r.6, "active": r.7 != 0,
    })
}

pub async fn list_workflows(
    State(s): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    let (_, mut tx) = principal(&s, &headers).await?;
    let rows: Vec<ScheduleRow> = sqlx::query_as(
        "SELECT id, name, kind, every_days, next_run, last_run, last_status, active \
         FROM workflow_schedule ORDER BY id",
    )
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    Ok(Json(Value::Array(rows.iter().map(schedule_json).collect())))
}

pub async fn workflow_last(
    State(s): State<AppState>,
    headers: HeaderMap,
    Path(wid): Path<i32>,
) -> Result<Json<Value>, ApiError> {
    let (_, mut tx) = principal(&s, &headers).await?;
    let row: Option<LastRow> = sqlx::query_as(
        "SELECT id, name, kind, every_days, next_run, last_run, last_status, active, last_result \
         FROM workflow_schedule WHERE id = $1",
    )
    .bind(wid)
    .fetch_optional(&mut *tx)
    .await?;
    tx.commit().await?;
    let Some((id, name, kind, every_days, next_run, last_run, last_status, active, last_result)) =
        row
    else {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "workflow not found"));
    };
    let r: ScheduleRow = (
        id,
        name,
        kind,
        every_days,
        next_run,
        last_run,
        last_status,
        active,
    );
    let mut out = schedule_json(&r);
    out["last_result"] = json!(last_result);
    Ok(Json(out))
}
