//! Port of GET /deals/{name}/wall (app/main.py get_deal_wall). Admin only, since the list names the people walled
//! off. Writes (PUT) stay on FastAPI.

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

pub async fn get_wall(
    State(s): State<AppState>,
    headers: HeaderMap,
    Path(name): Path<String>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let vis = Visibility::load(&mut tx, &p).await?;
    let row: Option<(Option<String>,)> = sqlx::query_as("SELECT wall FROM deal WHERE name = $1")
        .bind(&name)
        .fetch_optional(&mut *tx)
        .await?;
    // _wall_deal: a missing, out-of-scope or hidden deal answers 404 before the role check.
    let Some((wall,)) = row.filter(|_| vis.deal_allows(Some(&name))) else {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "deal not found"));
    };
    let role = p.role_on(&name);
    if role != "admin" {
        return Err(ApiError::new(
            StatusCode::FORBIDDEN,
            format!("role {role} cannot manage a deal's ethical wall"),
        ));
    }
    tx.commit().await?;
    // Python parse_wall: sorted, de-duplicated grants.
    let mut walled: Vec<String> = wall
        .and_then(|w| serde_json::from_str::<Vec<String>>(&w).ok())
        .unwrap_or_default();
    walled.sort();
    walled.dedup();
    Ok(Json(json!({ "deal": name, "walled": walled })))
}
