//! Port of GET /deals/{name}/meetings (app/main.py deal_meetings). Same deal wall as the deal itself:
//! a hidden deal answers 404. Calendar sync stays on FastAPI.

use crate::auth::principal;
use crate::error::ApiError;
use crate::visibility::Visibility;
use crate::AppState;
use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    Json,
};
use serde_json::{json, Value};

/// calendar_event row: title, starts_at, url, board, source.
type MeetingRow = (String, String, String, bool, String);

pub async fn deal_meetings(
    State(s): State<AppState>,
    headers: HeaderMap,
    Path(name): Path<String>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let vis = Visibility::load(&mut tx, &p).await?;
    // Python answers "no such deal" (not the shared helper's wording) for a missing or hidden deal.
    let exists: Option<(String,)> = sqlx::query_as("SELECT name FROM deal WHERE name = $1")
        .bind(&name)
        .fetch_optional(&mut *tx)
        .await?;
    if exists.is_none() || !vis.deal_allows(Some(&name)) {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "no such deal"));
    }
    let rows: Vec<MeetingRow> = sqlx::query_as(
        "SELECT title, starts_at, url, board, source FROM calendar_event \
         WHERE deal = $1 ORDER BY starts_at, id",
    )
    .bind(&name)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    let meetings: Vec<Value> = rows
        .into_iter()
        .map(|(title, starts_at, url, board, source)| {
            json!({ "title": title, "starts_at": starts_at, "url": url, "board": board, "source": source })
        })
        .collect();
    Ok(Json(json!({ "meetings": meetings })))
}
