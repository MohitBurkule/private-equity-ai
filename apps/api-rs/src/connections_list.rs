//! Port of GET /connections (app/main.py list_connections and _visible_connections). Saved connector setups for the
//! tenant, oldest first. A key scoped to deals sees only the connections on those deals. Tokens are never returned.

use crate::auth::principal;
use crate::error::ApiError;
use crate::AppState;
use axum::{extract::State, http::HeaderMap, Json};
use serde_json::{json, Value};

type ConnectionRow = (
    i32,
    String,
    Option<String>,
    Option<i32>,
    Option<String>,
    Option<String>,
);

pub async fn list_connections(
    State(s): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let rows: Vec<ConnectionRow> = sqlx::query_as(
        "SELECT id, connector, deal, interval_minutes, last_run, last_status FROM connection ORDER BY id",
    )
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    let out: Vec<Value> = rows
        .into_iter()
        .filter(|(_, _, deal, _, _, _)| match &p.deals {
            // walled keys see only the connections on their deals; a connection with no deal is never theirs
            Some(scope) => deal.as_ref().is_some_and(|d| scope.contains(d)),
            None => true,
        })
        .map(|(id, connector, deal, interval, last_run, last_status)| {
            json!({
                "id": id,
                "connector": connector,
                "deal": deal,
                "interval_minutes": interval,
                "last_run": last_run,
                "last_status": last_status,
            })
        })
        .collect();
    Ok(Json(Value::Array(out)))
}
