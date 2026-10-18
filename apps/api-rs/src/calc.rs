//! Port of GET /calc/periods (app/main.py calc_periods): the periods that have verified, visible facts for an entity,
//! oldest first, so a screen can default to periods that exist.

use crate::auth::principal;
use crate::error::ApiError;
use crate::visibility::Visibility;
use crate::AppState;
use axum::{
    extract::{Query, State},
    http::HeaderMap,
    Json,
};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::collections::{BTreeMap, BTreeSet};

pub async fn calc_periods(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let entity = q
        .get("entity")
        .ok_or_else(|| ApiError::missing_query("entity"))?;
    let vis = Visibility::load(&mut tx, &p).await?;
    let facts: Vec<(i32, String)> =
        sqlx::query_as("SELECT id, period FROM fact WHERE entity = $1 AND status = 'verified'")
            .bind(entity)
            .fetch_all(&mut *tx)
            .await?;
    let sources: Vec<(i32, String)> =
        sqlx::query_as("SELECT fact_id, document_id FROM fact_source ORDER BY id")
            .fetch_all(&mut *tx)
            .await?;
    tx.commit().await?;
    let mut docs: BTreeMap<i32, Vec<&str>> = BTreeMap::new();
    for (fact_id, doc_id) in &sources {
        docs.entry(*fact_id).or_default().push(doc_id.as_str());
    }
    let mut periods: BTreeSet<&str> = BTreeSet::new();
    for (id, period) in &facts {
        let ids = docs.get(id).map(Vec::as_slice).unwrap_or(&[]);
        if vis.fact_visible(ids) {
            periods.insert(period.as_str());
        }
    }
    Ok(Json(
        json!({ "entity": entity, "periods": periods.into_iter().collect::<Vec<_>>() }),
    ))
}
