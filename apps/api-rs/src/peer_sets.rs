//! Port of GET /deals/{name}/peer-sets (app/main.py peer_sets_list). Writes stay on FastAPI.
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

/// peer_set row: id, deal, name, target_id, items, dropped, refreshed_at.
type PeerSetRow = (i32, String, String, i32, String, String, String);

pub async fn list_peer_sets(
    State(s): State<AppState>,
    headers: HeaderMap,
    Path(name): Path<String>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let vis = Visibility::load(&mut tx, &p).await?;
    require_visible_deal(&mut tx, &vis, &name).await?;
    let rows: Vec<PeerSetRow> = sqlx::query_as(
        "SELECT id, deal, name, target_id, items, dropped, refreshed_at FROM peer_set \
         WHERE deal = $1 ORDER BY id",
    )
    .bind(&name)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    // Python peer_sets.out: items and dropped are stored as JSON text and sent parsed.
    let out: Vec<Value> = rows
        .into_iter()
        .map(|(id, deal, name, target_id, items, dropped, refreshed_at)| {
            json!({
                "id": id, "deal": deal, "name": name, "target_id": target_id,
                "items": serde_json::from_str::<Value>(&items).unwrap_or_else(|_| json!([])),
                "dropped": serde_json::from_str::<Value>(&dropped).unwrap_or_else(|_| json!([])),
                "refreshed_at": refreshed_at,
            })
        })
        .collect();
    Ok(Json(Value::Array(out)))
}
