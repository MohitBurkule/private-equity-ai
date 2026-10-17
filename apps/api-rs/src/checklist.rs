//! Port of GET /deals/{name}/checklist (app/main.py checklist_list). Writes stay on FastAPI.
//! Same deal wall as the deal itself: a hidden deal answers 404.

use crate::auth::principal;
use crate::error::ApiError;
use crate::visibility::{require_visible_deal, Visibility};
use crate::AppState;
use axum::{
    extract::{Path, State},
    http::HeaderMap,
    Json,
};
use serde_json::{json, Value};

/// deal_checklist_item row: id, deal, title, done, updated_at.
type ChecklistRow = (i32, String, String, bool, String);

pub async fn list_checklist(
    State(s): State<AppState>,
    headers: HeaderMap,
    Path(name): Path<String>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let vis = Visibility::load(&mut tx, &p).await?;
    require_visible_deal(&mut tx, &vis, &name).await?;
    let rows: Vec<ChecklistRow> = sqlx::query_as(
        "SELECT id, deal, title, done, updated_at FROM deal_checklist_item WHERE deal = $1 ORDER BY id",
    )
    .bind(&name)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    let out: Vec<Value> = rows
        .into_iter()
        .map(|(id, deal, title, done, updated_at)| {
            json!({ "id": id, "deal": deal, "title": title, "done": done, "updated_at": updated_at })
        })
        .collect();
    Ok(Json(Value::Array(out)))
}
