//! Port of GET /deals/{name}/notes and GET /targets/{tid}/notes (app/main.py). Writes stay on FastAPI.
//! Both answer 404 for a hidden deal, and a target whose company matches a hidden MNPI deal, as _visible_deal_or_404
//! and _target_or_404 do.

use crate::auth::principal;
use crate::error::ApiError;
use crate::names::normalise;
use crate::visibility::Visibility;
use crate::AppState;
use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    Json,
};
use serde_json::{json, Value};

/// deal_note row: id, deal, author, body, created_at, source_url, edited_at.
type DealNoteRow = (i32, String, String, String, String, Option<String>, String);
/// target_note row: id, target_id, author, body, created_at, edited_at.
type TargetNoteRow = (i32, i32, String, String, String, String);

pub async fn list_deal_notes(
    State(s): State<AppState>,
    headers: HeaderMap,
    Path(name): Path<String>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let vis = Visibility::load(&mut tx, &p).await?;
    let exists: Option<(String,)> = sqlx::query_as("SELECT name FROM deal WHERE name = $1")
        .bind(&name)
        .fetch_optional(&mut *tx)
        .await?;
    if exists.is_none() || !vis.deal_allows(Some(&name)) {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "deal not found"));
    }
    let rows: Vec<DealNoteRow> = sqlx::query_as(
        "SELECT id, deal, author, body, created_at, source_url, edited_at \
         FROM deal_note WHERE deal = $1 ORDER BY id",
    )
    .bind(&name)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    let out: Vec<Value> = rows
        .into_iter()
        .map(|(id, deal, author, body, created_at, source_url, edited_at)| {
            json!({
                "id": id, "deal": deal, "author": author, "body": body, "created_at": created_at,
                "source_url": source_url, "edited_at": non_empty(edited_at),
            })
        })
        .collect();
    Ok(Json(Value::Array(out)))
}

pub async fn list_target_notes(
    State(s): State<AppState>,
    headers: HeaderMap,
    Path(tid): Path<i32>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let vis = Visibility::load(&mut tx, &p).await?;
    let target: Option<(String,)> = sqlx::query_as("SELECT name FROM target WHERE id = $1")
        .bind(tid)
        .fetch_optional(&mut *tx)
        .await?;
    let Some((target_name,)) = target else {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "target not found"));
    };
    // mnpi_name_conflict: the target is hidden when it is the same company as a deal this key may not see.
    let key = normalise(&target_name);
    if vis.hidden_deal_names().any(|h| normalise(h) == key) {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "target not found"));
    }
    let rows: Vec<TargetNoteRow> = sqlx::query_as(
        "SELECT id, target_id, author, body, created_at, edited_at \
         FROM target_note WHERE target_id = $1 ORDER BY id",
    )
    .bind(tid)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    let out: Vec<Value> = rows
        .into_iter()
        .map(|(id, target_id, author, body, created_at, edited_at)| {
            json!({
                "id": id, "target_id": target_id, "author": author, "body": body,
                "created_at": created_at, "edited_at": non_empty(edited_at),
            })
        })
        .collect();
    Ok(Json(Value::Array(out)))
}

/// `edited_at or None` in Python: an empty string reads as never edited.
fn non_empty(s: String) -> Option<String> {
    (!s.is_empty()).then_some(s)
}
