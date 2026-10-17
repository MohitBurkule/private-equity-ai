//! Port of GET /alerts and GET /alerts/brief (app/main.py, app/alerts.py). Whole-tenant reads: a scoped key gets 403.
//! The status write (POST /alerts/{id}/status) stays on FastAPI and is relayed.

use crate::auth::principal;
use crate::error::ApiError;
use crate::AppState;
use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    Json,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::{BTreeMap, HashMap};

/// alert row: id, kind, severity, title, detail, fact_ids, status, created_at.
type AlertRow = (i32, String, String, String, String, String, String, String);

#[derive(Deserialize)]
pub struct ListQuery {
    status: Option<String>,
}

/// Python alert_dict.
fn alert_json(a: &AlertRow) -> Value {
    json!({
        "id": a.0, "kind": a.1, "severity": a.2, "title": a.3, "detail": a.4,
        "fact_ids": serde_json::from_str::<Value>(&a.5).unwrap_or_else(|_| json!([])),
        "status": a.6, "created_at": a.7,
    })
}

/// Python SEVERITIES = ("info", "warning", "critical"); the brief ranks critical first.
fn severity_rank(s: &str) -> usize {
    match s {
        "critical" => 0,
        "warning" => 1,
        "info" => 2,
        _ => 9,
    }
}

fn whole_tenant(p: &crate::auth::Principal) -> Result<(), ApiError> {
    if p.deals.is_some() {
        return Err(ApiError::new(
            StatusCode::FORBIDDEN,
            "alerts cover the whole tenant; use an unrestricted key",
        ));
    }
    Ok(())
}

pub async fn list_alerts(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<ListQuery>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    whole_tenant(&p)?;
    // Python `if status:`: an empty filter means no filter.
    let status = q.status.filter(|s| !s.is_empty());
    let rows: Vec<AlertRow> = sqlx::query_as(
        "SELECT id, kind, severity, title, detail, fact_ids, status, created_at FROM alert \
         WHERE ($1::text IS NULL OR status = $1) ORDER BY id DESC LIMIT 200",
    )
    .bind(status)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;
    Ok(Json(Value::Array(rows.iter().map(alert_json).collect())))
}

pub async fn alerts_brief(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, ApiError> {
    // FastAPI resolves the key, then the query, then runs the handler: 401, then 422, then the 403 below.
    let (p, mut tx) = principal(&s, &headers).await?;
    let since = q
        .get("since")
        .cloned()
        .ok_or_else(|| ApiError::missing_query("since"))?;
    whole_tenant(&p)?;
    let rows: Vec<AlertRow> = sqlx::query_as(
        "SELECT id, kind, severity, title, detail, fact_ids, status, created_at FROM alert \
         WHERE created_at >= $1 ORDER BY id DESC",
    )
    .bind(&since)
    .fetch_all(&mut *tx)
    .await?;
    tx.commit().await?;

    let mut by_kind: BTreeMap<&str, i64> = BTreeMap::new();
    let mut by_severity: BTreeMap<&str, i64> = BTreeMap::new();
    for a in &rows {
        *by_kind.entry(&a.1).or_insert(0) += 1;
        *by_severity.entry(&a.2).or_insert(0) += 1;
    }
    // sorted(rows, key=(rank, -id))[:10]: rows are already newest first, so a stable sort by rank keeps -id order.
    let mut top: Vec<&AlertRow> = rows.iter().collect();
    top.sort_by_key(|a| severity_rank(&a.2));
    let top: Vec<Value> = top.into_iter().take(10).map(alert_json).collect();
    Ok(Json(json!({
        "since": since, "total": rows.len(), "by_kind": by_kind, "by_severity": by_severity, "top": top,
    })))
}

#[cfg(test)]
mod tests {
    use super::severity_rank;

    #[test]
    fn critical_ranks_first_and_unknown_last() {
        assert!(severity_rank("critical") < severity_rank("warning"));
        assert!(severity_rank("warning") < severity_rank("info"));
        assert!(severity_rank("info") < severity_rank("other"));
    }
}
