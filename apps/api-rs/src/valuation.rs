//! Port of GET /valuation-rounds (app/main.py valuation_rounds_list). Import stays on FastAPI.
//! Deal-scoped keys get an empty list; rows whose source document the key cannot see are dropped.

use crate::auth::principal;
use crate::error::ApiError;
use crate::visibility::Visibility;
use crate::AppState;
use axum::{
    extract::{Query, State},
    http::HeaderMap,
    Json,
};
use rust_decimal::Decimal;
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize)]
pub struct RoundQuery {
    company: Option<String>,
}

/// valuation_round row: id, company, round_date, round_type, post_money, currency, document_id, line.
type RoundRow = (i32, String, String, String, Decimal, String, String, i32);

pub async fn list_rounds(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<RoundQuery>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    if p.deals.is_some() {
        return Ok(Json(json!([])));
    }
    let vis = Visibility::load(&mut tx, &p).await?;
    let company = q.company.filter(|c| !c.is_empty());
    let rows: Vec<RoundRow> = sqlx::query_as(
        "SELECT id, company, round_date, round_type, post_money, currency, document_id, line \
         FROM valuation_round WHERE ($1::text IS NULL OR company = $1) \
         ORDER BY round_date, id",
    )
    .bind(company)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    let out: Vec<Value> = rows
        .into_iter()
        .filter(|r| vis.doc_in_scope(&r.6))
        .map(|(id, company, round_date, round_type, post_money, currency, document_id, line)| {
            // Python str(Decimal): the stored scale is kept, so 1000 reads back as "1000.000000".
            json!({
                "id": id, "company": company, "round_date": round_date, "round_type": round_type,
                "post_money": post_money.to_string(), "currency": currency,
                "document_id": document_id, "line": line,
            })
        })
        .collect();
    Ok(Json(Value::Array(out)))
}
