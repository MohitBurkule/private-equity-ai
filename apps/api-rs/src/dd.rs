//! Port of GET /dd/requests, GET /dd/questions and GET /dd/summary (app/main.py). Writes stay on FastAPI.
//! Deal scope applies (_dd_scope_ok): a scoped key sees only its deals. The DD summary answers 404 for a deal the
//! key may not see, as dd_summary does.

use crate::auth::{principal, Principal};
use crate::error::ApiError;
use crate::AppState;
use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    Json,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::BTreeMap;

/// Python _dd_scope_ok: unscoped keys see every deal; scoped keys see their own list.
fn in_scope(p: &Principal, deal: &str) -> bool {
    p.deals.is_none() || p.deal_scope_has(deal)
}

/// Python round(100 * done / total, 1), or null with no requests.
pub fn pct_complete(done: i64, total: i64) -> Value {
    if total == 0 {
        return Value::Null;
    }
    let raw = 100.0 * done as f64 / total as f64;
    // Fixed-precision formatting rounds ties to even, as Python's round does.
    json!(format!("{raw:.1}").parse::<f64>().unwrap_or(raw))
}

/// dd_request row: id, deal, category, title, status, document_id, note, updated_at.
type RequestRow = (
    i32,
    String,
    String,
    String,
    String,
    Option<String>,
    Option<String>,
    String,
);

/// dd_question row: id, deal, request_id, question, status, answer, document_id, page, quote, asked_at, answered_at.
type QuestionRow = (
    i32,
    String,
    Option<i32>,
    String,
    String,
    Option<String>,
    Option<String>,
    Option<i32>,
    Option<String>,
    String,
    Option<String>,
);

fn request_json(r: &RequestRow) -> Value {
    json!({
        "id": r.0, "deal": r.1, "category": r.2, "title": r.3, "status": r.4,
        "document_id": r.5, "note": r.6, "updated_at": r.7,
    })
}

fn question_json(q: &QuestionRow) -> Value {
    json!({
        "id": q.0, "deal": q.1, "request_id": q.2, "question": q.3, "status": q.4, "answer": q.5,
        "document_id": q.6, "page": q.7, "quote": q.8, "asked_at": q.9, "answered_at": q.10,
    })
}

/// Python `if x:` on a query filter: an empty string means no filter.
fn filter(v: Option<String>) -> Option<String> {
    v.filter(|s| !s.is_empty())
}

#[derive(Deserialize)]
pub struct RequestsQuery {
    deal: Option<String>,
    status: Option<String>,
}

pub async fn list_requests(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<RequestsQuery>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let rows: Vec<RequestRow> = sqlx::query_as(
        "SELECT id, deal, category, title, status, document_id, note, updated_at FROM dd_request \
         WHERE ($1::text IS NULL OR deal = $1) AND ($2::text IS NULL OR status = $2) ORDER BY id",
    )
    .bind(filter(q.deal))
    .bind(filter(q.status))
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    let out: Vec<Value> = rows
        .iter()
        .filter(|r| in_scope(&p, &r.1))
        .map(request_json)
        .collect();
    Ok(Json(Value::Array(out)))
}

#[derive(Deserialize)]
pub struct QuestionsQuery {
    deal: Option<String>,
    status: Option<String>,
}

pub async fn list_questions(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<QuestionsQuery>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let rows: Vec<QuestionRow> = sqlx::query_as(
        "SELECT id, deal, request_id, question, status, answer, document_id, page, quote, asked_at, answered_at \
         FROM dd_question WHERE ($1::text IS NULL OR deal = $1) AND ($2::text IS NULL OR status = $2) ORDER BY id",
    )
    .bind(filter(q.deal))
    .bind(filter(q.status))
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    let out: Vec<Value> = rows
        .iter()
        .filter(|r| in_scope(&p, &r.1))
        .map(question_json)
        .collect();
    Ok(Json(Value::Array(out)))
}

#[derive(Deserialize)]
pub struct SummaryQuery {
    deal: String,
}

pub async fn dd_summary(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<SummaryQuery>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    if !in_scope(&p, &q.deal) {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "deal not found"));
    }
    let rows: Vec<RequestRow> = sqlx::query_as(
        "SELECT id, deal, category, title, status, document_id, note, updated_at FROM dd_request \
         WHERE deal = $1 ORDER BY id",
    )
    .bind(&q.deal)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;

    let mut cats: BTreeMap<&str, BTreeMap<&str, i64>> = BTreeMap::new();
    for r in &rows {
        let c = cats
            .entry(&r.2)
            .or_insert_with(|| BTreeMap::from([("open", 0), ("received", 0), ("waived", 0)]));
        *c.entry(&r.4).or_insert(0) += 1;
    }
    let done = rows.iter().filter(|r| r.4 != "open").count() as i64;
    let missing: Vec<Value> = rows
        .iter()
        .filter(|r| r.4 == "open")
        .map(request_json)
        .collect();
    Ok(Json(json!({
        "deal": q.deal,
        "total": rows.len(),
        "closed": done,
        "pct_complete": pct_complete(done, rows.len() as i64),
        "by_category": cats,
        "missing": missing,
    })))
}

#[cfg(test)]
mod tests {
    use super::pct_complete;
    use serde_json::json;

    #[test]
    fn pct_is_one_decimal_or_null() {
        assert_eq!(pct_complete(0, 0), json!(null));
        assert_eq!(pct_complete(1, 3), json!(33.3));
        assert_eq!(pct_complete(2, 2), json!(100.0));
    }
}
