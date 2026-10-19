//! Port of GET /webhooks (app/main.py webhook_list). Create and delete stay on FastAPI. The signing secret is
//! never returned, as in Python.

use crate::auth::principal;
use crate::compliance::GOVERN_ROLES;
use crate::error::ApiError;
use crate::AppState;
use axum::{extract::State, http::HeaderMap, http::StatusCode, Json};
use serde_json::{json, Value};

/// webhook_endpoint row: id, url, active.
type EndpointRow = (i32, String, bool);

pub async fn list_webhooks(
    State(s): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    // _require(who, "govern", ...) with no deal: the key's own role decides.
    if !GOVERN_ROLES.contains(&p.role.as_str()) {
        return Err(ApiError::new(
            StatusCode::FORBIDDEN,
            format!("role {} cannot manage webhooks", p.role),
        ));
    }
    let rows: Vec<EndpointRow> =
        sqlx::query_as("SELECT id, url, active FROM webhook_endpoint ORDER BY id")
            .fetch_all(&mut *tx)
            .await?;
    tx.commit().await?;
    let out: Vec<Value> = rows
        .into_iter()
        .map(|(id, url, active)| json!({ "id": id, "url": url, "active": active }))
        .collect();
    Ok(Json(Value::Array(out)))
}
