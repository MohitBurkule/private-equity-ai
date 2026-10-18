//! Port of GET /facts and POST /facts (app/main.py) with the citation gate from citations.rs and the deal wall and
//! source ACL from visibility.rs.

use crate::audit::log_event;
use crate::auth::principal;
use crate::citations::{is_outflow, locator_label, quote_in_page, verify_number, xlsx_location};
use crate::error::ApiError;
use crate::scope::require_writer;
use crate::visibility::Visibility;
use crate::AppState;
use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    Json,
};
use rust_decimal::Decimal;
use serde::{de, Deserialize, Deserializer};
use serde_json::{json, Value};
use std::str::FromStr;

/// Accepts a JSON number or string, as pydantic does for Decimal.
pub fn de_decimal<'de, D: Deserializer<'de>>(d: D) -> Result<Decimal, D::Error> {
    let v = Value::deserialize(d)?;
    let s = match &v {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        _ => return Err(de::Error::custom("value must be a number")),
    };
    Decimal::from_str(&s).map_err(de::Error::custom)
}

/// A Decimal read the way pydantic reads one: a JSON number or a string.
pub struct Dec(pub Decimal);

impl<'de> Deserialize<'de> for Dec {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        de_decimal(d).map(Dec)
    }
}

/// A fact value as Postgres stores it, Numeric(24, 6). sqlx reads a zero back unscaled, so every read site rescales.
pub fn stored(mut value: Decimal) -> Decimal {
    value.rescale(6);
    value
}

fn default_scale() -> Decimal {
    Decimal::ONE
}

fn default_basis() -> String {
    "GAAP".into()
}

#[derive(Deserialize)]
pub struct FactIn {
    entity: String,
    metric: String,
    period: String,
    #[serde(deserialize_with = "de_decimal")]
    value: Decimal,
    unit: String,
    document_id: String,
    page: i32,
    quote: String,
    #[serde(default = "default_scale", deserialize_with = "de_decimal")]
    scale: Decimal,
    #[serde(default = "default_basis")]
    basis: String,
}

#[derive(Deserialize)]
pub struct ListQuery {
    status: Option<String>,
    entity: Option<String>,
}

type FactRow = (
    i32,
    String,
    String,
    String,
    Decimal,
    String,
    String,
    String,
    Option<String>,
    Option<String>,
    Option<String>,
);
type SourceRow = (
    i32,
    String,
    i32,
    String,
    String,
    Option<String>,
    Option<String>,
    Option<String>,
);

pub async fn list_facts(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<ListQuery>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let vis = Visibility::load(&mut tx, &p).await?;
    let facts: Vec<FactRow> = sqlx::query_as(
        "SELECT id, entity, metric, period, value, unit, basis, status, reviewed_by, reviewed_at, review_note
         FROM fact WHERE ($1::text IS NULL OR status = $1) AND ($2::text IS NULL OR entity = $2) ORDER BY id",
    )
    .bind(q.status.as_deref())
    .bind(q.entity.as_deref())
    .fetch_all(&mut *tx)
    .await?;
    let sources: Vec<SourceRow> = sqlx::query_as(
        "SELECT fact_id, document_id, page, quote, kind, section, heading, anchor
         FROM fact_source ORDER BY id",
    )
    .fetch_all(&mut *tx)
    .await?;
    let mut out = Vec::with_capacity(facts.len());
    for f in &facts {
        let mine: Vec<&SourceRow> = sources.iter().filter(|s| s.0 == f.0).collect();
        let doc_ids: Vec<&str> = mine.iter().map(|s| s.1.as_str()).collect();
        if !vis.fact_visible(&doc_ids) {
            continue;
        }
        let srcs: Vec<Value> = mine
            .iter()
            .map(|s| {
                json!({
                    "document_id": s.1,
                    "page": s.2,
                    "locator": locator_label(s.2, s.5.as_deref(), s.6.as_deref(), &s.4, s.7.as_deref()),
                    "quote": s.3,
                })
            })
            .collect();
        out.push(json!({
            "id": f.0, "entity": f.1, "metric": f.2, "period": f.3, "value": stored(f.4).to_string(), "unit": f.5,
            "basis": f.6, "status": f.7, "reviewed_by": f.8, "reviewed_at": f.9, "review_note": f.10,
            "sources": srcs,
        }));
    }
    tx.commit().await?;
    Ok(Json(Value::Array(out)))
}

pub async fn create_fact(
    State(s): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<FactIn>,
) -> Result<impl IntoResponse, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    require_writer(&p)?;
    let vis = Visibility::load(&mut tx, &p).await?;

    // _own_doc: the document must be visible to this key (deal wall and ACL), or it is a 404.
    let doc: Option<(String, String, Option<String>)> =
        sqlx::query_as("SELECT id, kind, deal FROM document WHERE id = $1")
            .bind(&body.document_id)
            .fetch_optional(&mut *tx)
            .await?;
    let Some((doc_id, kind, deal)) = doc else {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "document not found"));
    };
    if !vis.deal_allows(deal.as_deref()) || !vis.acl_allows(&doc_id) {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "document not found"));
    }
    if let Some(d) = deal.as_deref().filter(|d| vis.visible_mnpi.contains(*d)) {
        log_event(
            &mut tx,
            &p.tenant,
            &format!("key:{}", p.key_id),
            "document.mnpi_access",
            &json!({ "doc_id": doc_id, "deal": d }),
        )
        .await?;
    }

    // add_verified_fact: page, quote and number must all check out before anything is stored.
    let page: Option<(String, Option<String>, String)> = sqlx::query_as(
        "SELECT text, label, method FROM page WHERE document_id = $1 AND number = $2",
    )
    .bind(&doc_id)
    .bind(body.page)
    .fetch_optional(&mut *tx)
    .await?;
    let cite_err = |m: &str| ApiError::new(StatusCode::UNPROCESSABLE_ENTITY, m);
    let Some((page_text, page_label, method)) = page else {
        return Err(cite_err(&format!(
            "page {} not found in document {}",
            body.page,
            &doc_id[..8.min(doc_id.len())]
        )));
    };
    if !quote_in_page(&body.quote, &page_text) {
        return Err(cite_err("quote not found on cited page"));
    }
    if !verify_number(
        body.value,
        &body.quote,
        body.scale,
        is_outflow(&body.metric),
    ) {
        return Err(cite_err("value does not match any number in the quote"));
    }
    let status = if method == "ocr" {
        "ocr_unverified"
    } else {
        "verified"
    };

    // make_source: workbooks cite a cell whose sheet must be this page's sheet.
    let (kind_col, heading, anchor, section) = if kind != "xlsx" {
        ("pdf".to_string(), None, None, None)
    } else {
        let (sheet, cell, row) = xlsx_location(&body.quote).ok_or_else(|| {
            cite_err("workbook quote must start with its cell, e.g. 'P&L!C14: 1,000'")
        })?;
        if page_label.as_deref() != Some(sheet.as_str()) {
            return Err(cite_err(
                "quote names a different sheet than the page cited",
            ));
        }
        ("xlsx".to_string(), Some(sheet), Some(cell), row)
    };

    let (fact_id,): (i32,) = sqlx::query_as(
        "INSERT INTO fact (tenant_id, entity, metric, period, value, unit, basis, status)
         VALUES (current_setting('app.tenant_id', true), $1, $2, $3, $4, $5, $6, $7) RETURNING id",
    )
    .bind(&body.entity)
    .bind(&body.metric)
    .bind(&body.period)
    .bind(body.value)
    .bind(&body.unit)
    .bind(&body.basis)
    .bind(status)
    .bind(&p.tenant)
    .fetch_one(&mut *tx)
    .await?;
    sqlx::query(
        "INSERT INTO fact_source (fact_id, document_id, page, quote, kind, section, heading, anchor)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
    )
    .bind(fact_id)
    .bind(&doc_id)
    .bind(body.page)
    .bind(&body.quote)
    .bind(&kind_col)
    .bind(section)
    .bind(heading)
    .bind(anchor)
    .execute(&mut *tx)
    .await?;

    log_event(
        &mut tx,
        &p.tenant,
        &format!("key:{}", p.key_id),
        "fact.create",
        &json!({ "fact_id": fact_id, "entity": body.entity, "metric": body.metric, "period": body.period }),
    )
    .await?;
    tx.commit().await?;
    Ok((
        StatusCode::CREATED,
        Json(json!({ "id": fact_id, "status": status })),
    ))
}
