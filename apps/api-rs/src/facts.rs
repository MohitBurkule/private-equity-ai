//! Port of GET /facts and POST /facts (app/main.py) with the citation gate from citations.rs.
//! Scope of this slice: unrestricted keys only. Deal-scoped or ACL-restricted keys get 501 until the deal wall
//! and source ACL are ported, so nothing is shown or written past a wall by accident.

use crate::audit::log_event;
use crate::auth::{principal, Principal, WRITE_ROLES};
use crate::citations::{is_outflow, locator_label, quote_in_page, verify_number, xlsx_location};
use crate::error::ApiError;
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
use sqlx::{Postgres, Transaction};
use std::str::FromStr;

/// Accepts a JSON number or string, as pydantic does for Decimal.
fn de_decimal<'de, D: Deserializer<'de>>(d: D) -> Result<Decimal, D::Error> {
    let v = Value::deserialize(d)?;
    let s = match &v {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        _ => return Err(de::Error::custom("value must be a number")),
    };
    Decimal::from_str(&s).map_err(de::Error::custom)
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

fn require_unrestricted(p: &Principal) -> Result<(), ApiError> {
    if p.restricted {
        return Err(ApiError::new(
            StatusCode::NOT_IMPLEMENTED,
            "deal-scoped keys not ported to the Rust API yet",
        ));
    }
    Ok(())
}

/// Matches `writer`: the key's role must carry the write capability.
fn require_writer(p: &Principal) -> Result<(), ApiError> {
    if !WRITE_ROLES.contains(&p.role.as_str()) {
        return Err(ApiError::new(StatusCode::FORBIDDEN, "role is read-only"));
    }
    Ok(())
}

/// Tenant-wide MNPI deals or ACL-restricted sources would hide rows from unrestricted keys. Refuse rather than leak.
async fn tenant_has_walls(tx: &mut Transaction<'_, Postgres>) -> Result<bool, sqlx::Error> {
    let (walls,): (bool,) = sqlx::query_as(
        "SELECT EXISTS (SELECT 1 FROM deal WHERE mnpi) OR EXISTS (SELECT 1 FROM document_source WHERE acl IS NOT NULL)",
    )
    .fetch_one(&mut **tx)
    .await?;
    Ok(walls)
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
    let (p, mut tx) = principal(&s.pool, &headers).await?;
    require_unrestricted(&p)?;
    if tenant_has_walls(&mut tx).await? {
        return Err(ApiError::new(
            StatusCode::NOT_IMPLEMENTED,
            "tenant has deal walls or ACLs; not ported yet",
        ));
    }
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
        let srcs: Vec<Value> = sources
            .iter()
            .filter(|s| s.0 == f.0)
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
            "id": f.0, "entity": f.1, "metric": f.2, "period": f.3, "value": f.4.to_string(), "unit": f.5,
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
    let (p, mut tx) = principal(&s.pool, &headers).await?;
    require_unrestricted(&p)?;
    require_writer(&p)?;
    if tenant_has_walls(&mut tx).await? {
        return Err(ApiError::new(
            StatusCode::NOT_IMPLEMENTED,
            "tenant has deal walls or ACLs; not ported yet",
        ));
    }

    // _own_doc: same 404 for missing and for another tenant (RLS hides the row either way).
    let doc: Option<(String, String)> =
        sqlx::query_as("SELECT id, kind FROM document WHERE id = $1")
            .bind(&body.document_id)
            .fetch_optional(&mut *tx)
            .await?;
    let Some((doc_id, kind)) = doc else {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "document not found"));
    };

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
