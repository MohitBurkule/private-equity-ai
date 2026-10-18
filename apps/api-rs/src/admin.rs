//! Port of the admin reads that take ADMIN_TOKEN (app/main.py admin_list_keys and admin_document_access). The token is
//! read from the environment per request, as FastAPI does. The write routes stay on FastAPI and are relayed.

use crate::audit::log_event;
use crate::error::ApiError;
use crate::AppState;
use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    Json,
};
use serde_json::{json, Value};
use sqlx::{Postgres, Transaction};
use std::collections::{BTreeMap, BTreeSet};

/// FastAPI's admin_token_ok: an unset token refuses everything; the comparison runs over every byte.
fn admin_token_ok(headers: &HeaderMap) -> bool {
    let Ok(expected) = std::env::var("ADMIN_TOKEN") else {
        return false;
    };
    if expected.is_empty() {
        return false;
    }
    let Some(presented) = headers.get("x-admin-token").and_then(|v| v.to_str().ok()) else {
        return false;
    };
    let (a, b) = (presented.as_bytes(), expected.as_bytes());
    a.len() == b.len() && a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

fn forbidden() -> ApiError {
    ApiError::new(StatusCode::FORBIDDEN, "admin token required")
}

/// A transaction bound to the tenant, after the tenant is confirmed to exist (404 otherwise).
async fn tenant_tx(s: &AppState, tenant: &str) -> Result<Transaction<'static, Postgres>, ApiError> {
    let mut tx = s.pool.begin().await?;
    sqlx::query("SELECT set_config('app.tenant_id', $1, true)")
        .bind(tenant)
        .execute(&mut *tx)
        .await?;
    let found: Option<(String,)> = sqlx::query_as("SELECT id FROM tenant WHERE id = $1")
        .bind(tenant)
        .fetch_optional(&mut *tx)
        .await?;
    if found.is_none() {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "tenant not found"));
    }
    Ok(tx)
}

type KeyRow = (String, bool, String, Option<String>, Option<String>);

/// Python acl.parse_deals: None stays null; otherwise the sorted set of non-empty names.
fn deal_list(raw: Option<String>) -> Value {
    match raw {
        None => Value::Null,
        Some(raw) => {
            let set: BTreeSet<&str> = raw
                .split(',')
                .map(str::trim)
                .filter(|d| !d.is_empty())
                .collect();
            json!(set)
        }
    }
}

/// Python acl.parse_deal_roles read into a dict: pairs sorted, a repeated deal keeps its last role.
fn deal_roles(raw: Option<String>) -> Value {
    let mut pairs: Vec<(String, String)> = raw
        .unwrap_or_default()
        .split(',')
        .filter(|p| !p.trim().is_empty())
        .filter_map(|p| {
            p.split_once(':')
                .map(|(d, r)| (d.to_string(), r.to_string()))
        })
        .collect();
    pairs.sort();
    let map: BTreeMap<String, String> = pairs.into_iter().collect();
    json!(map)
}

/// GET /admin/tenants/{tenant_id}/keys: every key with its wall, named by key_id (first 12 hex of its hash).
pub async fn list_keys(
    State(s): State<AppState>,
    headers: HeaderMap,
    Path(tenant): Path<String>,
) -> Result<Json<Value>, ApiError> {
    if !admin_token_ok(&headers) {
        return Err(forbidden());
    }
    let mut tx = tenant_tx(&s, &tenant).await?;
    let rows: Vec<KeyRow> = sqlx::query_as(
        "SELECT key_hash, revoked, role, deals, deal_roles FROM api_key WHERE tenant_id = $1 ORDER BY key_hash",
    )
    .bind(&tenant)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    let keys: Vec<Value> = rows
        .into_iter()
        .map(|(hash, revoked, role, deals, roles)| {
            json!({
                "key_id": &hash[..12.min(hash.len())],
                "role": role,
                "revoked": revoked,
                "deals": deal_list(deals),
                "deal_roles": deal_roles(roles),
            })
        })
        .collect();
    Ok(Json(json!({ "keys": keys })))
}

type SourceRow = (String, String, Option<String>, String, String);

/// GET /admin/tenants/{tenant_id}/document-access: synced documents whose source names who may read them.
pub async fn document_access(
    State(s): State<AppState>,
    headers: HeaderMap,
    Path(tenant): Path<String>,
) -> Result<Json<Value>, ApiError> {
    if !admin_token_ok(&headers) {
        return Err(forbidden());
    }
    let mut tx = tenant_tx(&s, &tenant).await?;
    let rows: Vec<SourceRow> = sqlx::query_as(
        "SELECT d.id, d.filename, d.deal, s.connector, s.acl FROM document_source s \
         JOIN document d ON d.id = s.document_id \
         WHERE s.tenant_id = $1 AND s.acl IS NOT NULL ORDER BY d.filename",
    )
    .bind(&tenant)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    let docs: Vec<Value> = rows
        .into_iter()
        .map(|(id, filename, deal, connector, acl)| {
            json!({
                "document_id": id,
                "filename": filename,
                "deal": deal,
                "connector": connector,
                "grants": serde_json::from_str::<Value>(&acl).unwrap_or(Value::Null),
            })
        })
        .collect();
    let restricted = docs.len();
    Ok(Json(json!({ "documents": docs, "restricted": restricted })))
}

/// DELETE /admin/keys/{kid}: revoke the one key whose id matches. Python counts the matches across every tenant, so
/// an id that names two keys answers 404 and changes nothing. A key that is already revoked stays revoked.
pub async fn revoke_key(
    State(s): State<AppState>,
    headers: HeaderMap,
    Path(kid): Path<String>,
) -> Result<Json<Value>, ApiError> {
    if !admin_token_ok(&headers) {
        return Err(forbidden());
    }
    let mut tx = s.pool.begin().await?;
    let matches: Vec<(String,)> = sqlx::query_as(
        "SELECT key_hash FROM api_key WHERE substr(key_hash, 1, 12) = $1 FOR UPDATE",
    )
    .bind(&kid)
    .fetch_all(&mut *tx)
    .await?;
    let [(hash,)] = matches.as_slice() else {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "key not found"));
    };
    sqlx::query("UPDATE api_key SET revoked = true WHERE key_hash = $1")
        .bind(hash)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    Ok(Json(json!({ "revoked": kid })))
}

/// PUT /admin/tenants/{tenant_id}/pii-redaction: set the tenant's PII flag. Audited under the tenant as "admin".
/// The tenant is looked up before the body is read, as FastAPI does: an unknown tenant answers 404 first.
pub async fn set_pii_redaction(
    State(s): State<AppState>,
    headers: HeaderMap,
    Path(tenant): Path<String>,
    Json(body): Json<Value>,
) -> Result<Json<Value>, ApiError> {
    if !admin_token_ok(&headers) {
        return Err(forbidden());
    }
    let mut tx = tenant_tx(&s, &tenant).await?;
    let Some(on) = body.get("on").and_then(Value::as_bool) else {
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "body must be {\"on\": true or false}",
        ));
    };
    sqlx::query("UPDATE tenant SET pii_redaction = $2 WHERE id = $1")
        .bind(&tenant)
        .bind(on)
        .execute(&mut *tx)
        .await?;
    log_event(
        &mut tx,
        &tenant,
        "admin",
        "tenant.pii_redaction",
        &json!({ "on": on }),
    )
    .await?;
    tx.commit().await?;
    Ok(Json(json!({ "tenant_id": tenant, "pii_redaction": on })))
}
