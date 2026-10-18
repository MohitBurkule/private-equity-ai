//! Port of app/audit.py: one sha256 hash chain per tenant. The payload string is hashed as stored, so it must match
//! what Python writes: keys sorted, ", " and ": " separators.

use crate::auth::principal;
use crate::error::ApiError;
use crate::AppState;
use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    Json,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use sqlx::{Postgres, Transaction};
use std::collections::HashMap;

/// Python json.dumps(sort_keys=True) layout. Non-ASCII text is not escaped (Python would write \uXXXX).
pub fn py_json(v: &Value) -> String {
    match v {
        Value::Object(m) => {
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort();
            let parts: Vec<String> = keys
                .iter()
                .map(|k| format!("{}: {}", serde_json::to_string(k).unwrap(), py_json(&m[*k])))
                .collect();
            format!("{{{}}}", parts.join(", "))
        }
        Value::Array(a) => format!("[{}]", a.iter().map(py_json).collect::<Vec<_>>().join(", ")),
        other => other.to_string(),
    }
}

fn digest(prev: &str, ts: &str, actor: &str, action: &str, payload: &str) -> String {
    hex::encode(Sha256::digest(
        [prev, ts, actor, action, payload].join("\x1f").as_bytes(),
    ))
}

pub async fn log_event(
    tx: &mut Transaction<'_, Postgres>,
    tenant: &str,
    actor: &str,
    action: &str,
    payload: &Value,
) -> Result<(), sqlx::Error> {
    let prev: Option<(String,)> = sqlx::query_as(
        "SELECT hash FROM audit_event WHERE tenant_id = $1 ORDER BY id DESC LIMIT 1",
    )
    .bind(tenant)
    .fetch_optional(&mut **tx)
    .await?;
    let prev = prev.map(|r| r.0).unwrap_or_else(|| "0".repeat(64));
    let ts = chrono::Utc::now()
        .format("%Y-%m-%dT%H:%M:%S%.6f+00:00")
        .to_string();
    let body = py_json(payload);
    let hash = digest(&prev, &ts, actor, action, &body);
    sqlx::query("INSERT INTO audit_event (tenant_id, ts, actor, action, payload, prev_hash, hash) VALUES ($1,$2,$3,$4,$5,$6,$7)")
        .bind(tenant)
        .bind(&ts)
        .bind(actor)
        .bind(action)
        .bind(&body)
        .bind(&prev)
        .bind(&hash)
        .execute(&mut **tx)
        .await?;
    Ok(())
}

pub(crate) type AuditRow = (i32, String, String, String, String);
type ChainRow = (i32, String, String, String, String, String, String);

/// FastAPI's `limit: int = Query(100, ge=1, le=500)`, checked before the handler runs.
fn audit_limit(raw: Option<&String>) -> Result<i64, ApiError> {
    let Some(raw) = raw else { return Ok(100) };
    let n: i64 = raw.parse().map_err(|_| ApiError::query_int("limit", raw))?;
    if n < 1 {
        return Err(ApiError::query_below("limit", raw, 1));
    }
    if n > 500 {
        return Err(ApiError::query_above("limit", raw, 500));
    }
    Ok(n)
}

/// Port of GET /audit (app/main.py audit_list): the tenant's chain, newest first, whole-tenant keys only.
pub async fn list_audit(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    // Validation runs before the handler in FastAPI, so a bad limit answers 422 even for a scoped key.
    let limit = audit_limit(q.get("limit"))?;
    if p.deals.is_some() {
        return Err(ApiError::new(
            StatusCode::FORBIDDEN,
            "the audit trail covers the whole tenant; use an unrestricted key",
        ));
    }
    // Python `if action:`: an empty filter means no filter.
    let action = q.get("action").filter(|a| !a.is_empty()).cloned();
    let rows: Vec<AuditRow> = sqlx::query_as(
        "SELECT id, ts, actor, action, payload FROM audit_event \
         WHERE ($1::text IS NULL OR action = $1) ORDER BY id DESC LIMIT $2",
    )
    .bind(action)
    .bind(limit)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    let items: Vec<Value> = rows
        .into_iter()
        .map(|(id, ts, actor, action, payload)| {
            json!({
                "id": id,
                "ts": ts,
                "actor": actor,
                "action": action,
                "payload": serde_json::from_str::<Value>(&payload).unwrap_or(Value::Null),
            })
        })
        .collect();
    Ok(Json(json!({ "items": items })))
}

/// Port of GET /audit/verify (app/main.py audit_verify): walk the tenant chain from the start and report the first
/// row whose link or digest does not hold. Any key of the tenant may ask; the chain covers every deal.
pub async fn verify_audit(
    State(s): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    let (_p, mut tx) = principal(&s, &headers).await?;
    let rows: Vec<ChainRow> = sqlx::query_as(
        "SELECT id, ts, actor, action, payload, prev_hash, hash FROM audit_event ORDER BY id",
    )
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    let mut prev = "0".repeat(64);
    for (id, ts, actor, action, payload, prev_hash, hash) in rows {
        if prev_hash != prev || hash != digest(&prev, &ts, &actor, &action, &payload) {
            return Ok(Json(json!({ "ok": false, "first_bad_id": id })));
        }
        prev = hash;
    }
    Ok(Json(json!({ "ok": true, "first_bad_id": null })))
}
