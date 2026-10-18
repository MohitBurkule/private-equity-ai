//! Port of GET /facts/derived (app/derived.py derive, app/main.py fact_derived). A derived value is recomputed on each
//! read from cited, verified, visible component facts; nothing is stored. Errors are FastAPI's 422 with the message.

use crate::auth::principal;
use crate::error::ApiError;
use crate::visibility::Visibility;
use crate::AppState;
use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    Json,
};
use rust_decimal::Decimal;
use serde_json::{json, Value};
use sqlx::{Postgres, Transaction};
use std::collections::{BTreeSet, HashMap};

/// Python derived.SUMS: formula name -> component metrics, summed.
const SUMS: [(&str, [&str; 2]); 1] = [(
    "ebitda",
    ["operating_income", "depreciation_and_amortization"],
)];

/// One component: fact id, metric, value, and the citation fields derive keeps (document, page, quote).
pub struct Component {
    fact_id: i32,
    metric: &'static str,
    value: Decimal,
    sources: Vec<Value>,
}

pub struct Derived {
    formula: String,
    entity: String,
    period: String,
    unit: String,
    value: Decimal,
    components: Vec<Component>,
}

/// Python derive(): a ValueError becomes Err(message). The first fact by id stands for each metric, as the
/// Python `.first()` does on a query with no ordering.
pub async fn derive(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    formula: &str,
    entity: &str,
    period: &str,
) -> Result<Derived, String> {
    let Some((_, metrics)) = SUMS.iter().find(|(name, _)| *name == formula) else {
        return Err(format!("unknown formula: {formula}"));
    };
    let mut parts: Vec<Component> = Vec::new();
    let mut units: BTreeSet<String> = BTreeSet::new();
    for metric in metrics {
        let row: Option<(i32, String, Decimal)> = sqlx::query_as(
            "SELECT id, unit, value FROM fact WHERE entity = $1 AND period = $2 AND metric = $3 \
             AND status = 'verified' ORDER BY id LIMIT 1",
        )
        .bind(entity)
        .bind(period)
        .bind(*metric)
        .fetch_optional(&mut **tx)
        .await
        .map_err(|e| format!("db error: {e}"))?;
        let Some((id, unit, value)) = row else {
            return Err(format!(
                "{metric} for {entity} {period} is not a verified, cited, visible fact"
            ));
        };
        let srcs: Vec<(String, i32, String)> = sqlx::query_as(
            "SELECT document_id, page, quote FROM fact_source WHERE fact_id = $1 ORDER BY id",
        )
        .bind(id)
        .fetch_all(&mut **tx)
        .await
        .map_err(|e| format!("db error: {e}"))?;
        let doc_ids: Vec<&str> = srcs.iter().map(|s| s.0.as_str()).collect();
        // Python: `not f.sources or not fact_visible(f, scope)`.
        if doc_ids.is_empty() || !vis.fact_visible(&doc_ids) {
            return Err(format!(
                "{metric} for {entity} {period} is not a verified, cited, visible fact"
            ));
        }
        units.insert(unit);
        parts.push(Component {
            fact_id: id,
            metric,
            value,
            sources: srcs
                .into_iter()
                .map(|(document_id, page, quote)| json!({ "document_id": document_id, "page": page, "quote": quote }))
                .collect(),
        });
    }
    if units.len() != 1 {
        let listed: Vec<&str> = units.iter().map(String::as_str).collect();
        return Err(format!(
            "components of {formula} are in different units: {}",
            listed.join(", ")
        ));
    }
    let value: Decimal = parts.iter().fold(Decimal::ZERO, |acc, c| acc + c.value);
    Ok(Derived {
        formula: formula.into(),
        entity: entity.into(),
        period: period.into(),
        unit: units.into_iter().next().unwrap_or_default(),
        value,
        components: parts,
    })
}

pub async fn fact_derived(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, ApiError> {
    // FastAPI resolves the key (401), then reports every missing parameter in one 422, then runs the handler.
    let (p, mut tx) = principal(&s, &headers).await?;
    let missing: Vec<Value> = ["formula", "entity", "period"]
        .iter()
        .filter(|name| !q.contains_key(**name))
        .map(|name| json!({ "type": "missing", "loc": ["query", name], "msg": "Field required", "input": null }))
        .collect();
    if !missing.is_empty() {
        return Err(ApiError(
            StatusCode::UNPROCESSABLE_ENTITY,
            "validation error".into(),
            Some(Value::Array(missing)),
        ));
    }
    let vis = Visibility::load(&mut tx, &p).await?;
    let d = match derive(&mut tx, &vis, &q["formula"], &q["entity"], &q["period"]).await {
        Ok(d) => d,
        Err(msg) => return Err(ApiError::new(StatusCode::UNPROCESSABLE_ENTITY, msg)),
    };
    tx.commit().await?;
    let components: Vec<Value> = d
        .components
        .iter()
        .map(|c| {
            json!({ "fact_id": c.fact_id, "metric": c.metric, "value": c.value.to_string(), "sources": c.sources })
        })
        .collect();
    Ok(Json(json!({
        "formula": d.formula, "entity": d.entity, "period": d.period, "unit": d.unit,
        "value": d.value.to_string(), "components": components,
    })))
}
