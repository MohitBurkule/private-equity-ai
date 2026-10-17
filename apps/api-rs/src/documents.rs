//! Port of GET /documents and GET /documents/{id}/pages/{n} (app/main.py). Upload and extraction are not ported.

use crate::auth::principal;
use crate::error::ApiError;
use crate::scope::{ensure_no_walls, require_unrestricted};
use crate::AppState;
use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    Json,
};
use serde_json::{json, Value};

pub async fn list_documents(
    State(s): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s.pool, &headers).await?;
    require_unrestricted(&p)?;
    ensure_no_walls(&mut tx).await?;
    let rows: Vec<(String, String, i32, Option<String>)> =
        sqlx::query_as("SELECT id, filename, n_pages, deal FROM document ORDER BY id")
            .fetch_all(&mut *tx)
            .await?;
    tx.commit().await?;
    let out: Vec<Value> = rows
        .into_iter()
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
    require_unrestricted(&p)?;
    ensure_no_walls(&mut tx).await?;
    // _own_doc: missing and other-tenant documents look the same (RLS hides the row).
    let doc: Option<(String,)> = sqlx::query_as("SELECT id FROM document WHERE id = $1")
        .bind(&doc_id)
        .fetch_optional(&mut *tx)
        .await?;
    if doc.is_none() {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "document not found"));
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
