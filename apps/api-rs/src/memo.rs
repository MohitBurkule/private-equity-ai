//! Port of GET /memo/templates and GET /memo/versions (app/main.py). Memo text itself (GET /memo, /memo/sections)
//! needs the comps and legal modules and is still relayed to FastAPI; so is GET /memo/versions/{id}, because its
//! path would shadow the relayed /memo/versions/diff.

use crate::auth::principal;
use crate::error::ApiError;
use crate::AppState;
use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    Json,
};
use serde_json::{json, Value};

/// Built-in templates (app/memo_templates.py TEMPLATES), in the order FastAPI lists them.
const BUILT_IN: &[(&str, &[&str])] = &[
    ("ic", &["financial", "derived", "risks", "rules"]),
    ("snapshot", &["derived", "risks"]),
];

pub async fn list_templates(
    State(s): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    let (_, mut tx) = principal(&s, &headers).await?;
    let rows: Vec<(String, String, Option<String>, Option<String>)> =
        sqlx::query_as("SELECT name, sections, headings, intro FROM memo_template ORDER BY name")
            .fetch_all(&mut *tx)
            .await?;
    tx.commit().await?;

    // Python builds a dict: built-ins first, then the firm's rows by name. A firm row never shares a built-in name
    // (the save route refuses it), so the two sets do not overlap.
    let mut items: Vec<Value> = BUILT_IN
        .iter()
        .map(|(name, sections)| {
            json!({ "name": name, "sections": sections, "built_in": true, "headings": {}, "intro": "" })
        })
        .collect();
    for (name, sections, headings, intro) in rows {
        let sections: Value = serde_json::from_str(&sections).unwrap_or(Value::Array(vec![]));
        let headings: Value =
            serde_json::from_str(headings.as_deref().unwrap_or("{}")).unwrap_or(json!({}));
        items.push(json!({
            "name": name, "sections": sections, "built_in": false,
            "headings": headings, "intro": intro.unwrap_or_default(),
        }));
    }
    Ok(Json(json!({ "items": items })))
}

#[derive(serde::Deserialize)]
pub struct EntityQuery {
    entity: String,
}

/// Matches `_whole_tenant`: a saved memo covers the whole tenant, so only an unscoped key may read versions.
pub async fn list_versions(
    State(s): State<AppState>,
    headers: HeaderMap,
    axum::extract::Query(q): axum::extract::Query<EntityQuery>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    if p.deals.is_some() {
        return Err(ApiError::new(
            StatusCode::FORBIDDEN,
            "memo versions cover the whole tenant; use an unrestricted key",
        ));
    }
    let rows: Vec<(i32, i32, String, String)> = sqlx::query_as(
        "SELECT id, number, created_by, created_at FROM memo_version WHERE entity = $1 ORDER BY number",
    )
    .bind(&q.entity)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    let items: Vec<Value> = rows
        .into_iter()
        .map(|(id, number, created_by, created_at)| {
            json!({ "id": id, "number": number, "created_by": created_by, "created_at": created_at })
        })
        .collect();
    Ok(Json(json!({ "items": items })))
}
