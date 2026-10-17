//! Port of GET /documents and GET /documents/{id}/pages/{n} (app/main.py). Upload and extraction are not ported.

use crate::audit::log_event;
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

/// Python list_documents: the deal wall and the source ACL both apply, so hidden filenames are not listed.
pub async fn list_documents(
    State(s): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s.pool, &headers).await?;
    let vis = Visibility::load(&mut tx, &p).await?;
    let rows: Vec<(String, String, i32, Option<String>)> =
        sqlx::query_as("SELECT id, filename, n_pages, deal FROM document ORDER BY id")
            .fetch_all(&mut *tx)
            .await?;
    tx.commit().await?;
    let out: Vec<Value> = rows
        .into_iter()
        // Same test as get_page: a listed name must also open, so ACL-restricted filenames stay hidden.
        .filter(|(id, _, _, deal)| vis.deal_allows(deal.as_deref()) && vis.acl_allows(id))
        .map(|(id, filename, n_pages, deal)| json!({ "id": id, "filename": filename, "n_pages": n_pages, "deal": deal }))
        .collect();
    Ok(Json(Value::Array(out)))
}

pub async fn get_page(
    State(s): State<AppState>,
    headers: HeaderMap,
    Path((doc_id, number)): Path<(String, i32)>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s.pool, &headers).await?;
    let vis = Visibility::load(&mut tx, &p).await?;
    // _own_doc: missing, other-tenant, walled and ACL-hidden documents all get the same 404.
    let doc: Option<(String, Option<String>)> =
        sqlx::query_as("SELECT id, deal FROM document WHERE id = $1")
            .bind(&doc_id)
            .fetch_optional(&mut *tx)
            .await?;
    let Some((_, deal)) = doc else {
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
    let row: Option<(String, String, Option<f64>)> = sqlx::query_as(
        "SELECT text, method, ocr_confidence FROM page WHERE document_id = $1 AND number = $2",
    )
    .bind(&doc_id)
    .bind(number)
    .fetch_optional(&mut *tx)
    .await?;
    let Some((text, method, ocr_confidence)) = row else {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "page not found"));
    };
    tx.commit().await?;
    Ok(Json(json!({
        "document_id": doc_id, "page": number, "text": text, "method": method, "ocr_confidence": ocr_confidence,
    })))
}
