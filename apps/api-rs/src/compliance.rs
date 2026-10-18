//! Port of GET /compliance/access-report (app/main.py access_report): every logged audit event that names one deal,
//! with a count per actor. Whole-tenant keys only, and the caller must hold the "govern" capability on that deal.
//! Document reads are not logged, so they do not appear.

use crate::audit::AuditRow;
use crate::auth::{principal, Principal};
use crate::error::ApiError;
use crate::AppState;
use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    Json,
};
use serde_json::{json, Value};
use std::collections::HashMap;

/// Python acl.CAPABILITIES["govern"].
const GOVERN_ROLES: &[&str] = &["admin", "partner", "vp", "compliance"];

/// Python Principal.role_on: the role a per-deal override gives on this deal, else the key role.
fn role_on<'a>(p: &'a Principal, deal: &str) -> &'a str {
    p.deal_roles
        .iter()
        .find(|(d, _)| d == deal)
        .map_or(p.role.as_str(), |(_, r)| r.as_str())
}

/// Python `limit: int = Query(500, ge=1, le=5000)`.
fn report_limit(raw: Option<&String>) -> Result<usize, ApiError> {
    let Some(raw) = raw else { return Ok(500) };
    let n: i64 = raw.parse().map_err(|_| ApiError::query_int("limit", raw))?;
    if n < 1 {
        return Err(ApiError::query_below("limit", raw, 1));
    }
    if n > 5000 {
        return Err(ApiError::query_above("limit", raw, 5000));
    }
    Ok(n as usize)
}

pub async fn access_report(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    // Validation runs before the handler in FastAPI, so a missing deal or a bad limit answers 422 first.
    let deal = q
        .get("deal")
        .ok_or_else(|| ApiError::missing_query("deal"))?
        .clone();
    let limit = report_limit(q.get("limit"))?;
    if p.deals.is_some() {
        return Err(ApiError::new(
            StatusCode::FORBIDDEN,
            "the access report covers the whole tenant; use an unrestricted key",
        ));
    }
    let role = role_on(&p, &deal);
    if !GOVERN_ROLES.contains(&role) {
        return Err(ApiError::new(
            StatusCode::FORBIDDEN,
            format!("role {role} cannot read the access report"),
        ));
    }
    let rows: Vec<AuditRow> = sqlx::query_as(
        "SELECT id, ts, actor, action, payload FROM audit_event ORDER BY id DESC LIMIT $1",
    )
    .bind((limit * 10) as i64)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    let mut events: Vec<Value> = Vec::new();
    let mut by_actor: Vec<(String, i64)> = Vec::new();
    for (_, ts, actor, action, payload) in rows {
        if events.len() >= limit {
            break;
        }
        let payload: Value = serde_json::from_str(&payload).unwrap_or(Value::Null);
        let names_deal = payload.get("name").and_then(Value::as_str) == Some(deal.as_str())
            || payload.get("deal").and_then(Value::as_str) == Some(deal.as_str())
            || payload
                .get("deals")
                .and_then(Value::as_array)
                .is_some_and(|ds| ds.iter().any(|d| d.as_str() == Some(deal.as_str())));
        if names_deal {
            match by_actor.iter_mut().find(|(a, _)| *a == actor) {
                Some((_, n)) => *n += 1,
                None => by_actor.push((actor.clone(), 1)),
            }
            events.push(json!({"ts": ts, "actor": actor, "action": action, "payload": payload}));
        }
    }
    let by_actor: serde_json::Map<String, Value> =
        by_actor.into_iter().map(|(a, n)| (a, json!(n))).collect();
    Ok(Json(json!({
        "deal": deal,
        "events": events,
        "by_actor": by_actor,
        "note": "Logged actions only. Document reads are not in the audit trail.",
    })))
}
