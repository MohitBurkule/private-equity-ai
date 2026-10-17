//! Port of GET /deals/{name}/snapshot (app/main.py deal_snapshot, ic_review, dd_summary). Read-only.
//! Built from the same rows the workspace reads, so the numbers agree with the screens.

use crate::auth::principal;
use crate::error::ApiError;
use crate::visibility::{require_visible_deal, Visibility};
use crate::AppState;
use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    Json,
};
use chrono::{DateTime, NaiveDateTime, Utc};
use serde_json::{json, Value};

/// ic_decision row: id, deal, outcome, rationale, dissent, dissenter, recorded_at.
type DecisionRow = (
    i32,
    String,
    String,
    String,
    Option<String>,
    Option<String>,
    String,
);

/// Python datetime.fromisoformat for the timestamps this app writes: offset-aware, or naive (read as UTC here).
fn instant(s: &str) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(s)
        .map(|d| d.with_timezone(&Utc))
        .ok()
        .or_else(|| {
            NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S%.f")
                .ok()
                .map(|n| n.and_utc())
        })
}

fn decision_json(d: &DecisionRow) -> Value {
    json!({
        "id": d.0, "deal": d.1, "outcome": d.2, "rationale": d.3, "dissent": d.4,
        "dissenter": d.5, "recorded_at": d.6,
    })
}

pub async fn deal_snapshot(
    State(s): State<AppState>,
    headers: HeaderMap,
    Path(name): Path<String>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let vis = Visibility::load(&mut tx, &p).await?;
    require_visible_deal(&mut tx, &vis, &name).await?;

    let deal: (String, String, Option<String>, Option<String>, bool) =
        sqlx::query_as("SELECT name, stage, sic, sponsor, legal_hold FROM deal WHERE name = $1")
            .bind(&name)
            .fetch_one(&mut *tx)
            .await?;

    // ic_review: latest decision (last by id), dissents on file, documents filed after it.
    let decisions: Vec<DecisionRow> = sqlx::query_as(
        "SELECT id, deal, outcome, rationale, dissent, dissenter, recorded_at \
         FROM ic_decision WHERE deal = $1 ORDER BY id",
    )
    .bind(&name)
    .fetch_all(&mut *tx)
    .await?;
    // Documents on the deal, visible to the key (the deal is visible, so this is the deal's own list).
    let mut docs: Vec<(String, String, Option<String>)> =
        sqlx::query_as("SELECT id, filename, created_at FROM document WHERE deal = $1")
            .bind(&name)
            .fetch_all(&mut *tx)
            .await?;
    let latest = decisions.last();
    let dissents = decisions
        .iter()
        .filter(|d| d.4.as_deref().is_some_and(|x| !x.is_empty()))
        .count();
    let mut since: Vec<Value> = Vec::new();
    if let Some(latest) = latest {
        // Compare instants, not strings. A timestamp that will not parse is a server error, as in Python.
        let cut = instant(&latest.6)
            .ok_or_else(|| ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, "internal error"))?;
        docs.sort_by(|a, b| {
            a.2.as_deref()
                .unwrap_or("")
                .cmp(b.2.as_deref().unwrap_or(""))
        });
        for (id, filename, created_at) in &docs {
            let Some(created) = created_at.as_deref().filter(|c| !c.is_empty()) else {
                continue;
            };
            if instant(created).is_some_and(|t| t > cut) {
                since.push(
                    json!({ "document_id": id, "filename": filename, "created_at": created_at }),
                );
            }
        }
    }

    // Documents list: newest first by created_at, top five.
    docs.sort_by(|a, b| {
        b.2.as_deref()
            .unwrap_or("")
            .cmp(a.2.as_deref().unwrap_or(""))
    });
    let latest_docs: Vec<Value> = docs
        .iter()
        .take(5)
        .map(|(id, filename, _)| json!({ "id": id, "filename": filename }))
        .collect();

    // dd_summary: total, closed (status not open), percent complete to one decimal.
    let dd_rows: Vec<(String,)> = sqlx::query_as("SELECT status FROM dd_request WHERE deal = $1")
        .bind(&name)
        .fetch_all(&mut *tx)
        .await?;
    let dd_total = dd_rows.len();
    let dd_closed = dd_rows.iter().filter(|r| r.0 != "open").count();
    let pct: Value = if dd_total == 0 {
        Value::Null
    } else {
        // Python round(x, 1): same ties-to-even result as Rust's fixed-precision formatting.
        let raw = 100.0 * dd_closed as f64 / dd_total as f64;
        json!(format!("{raw:.1}").parse::<f64>().unwrap_or(raw))
    };

    let open_alerts: (i64,) =
        sqlx::query_as("SELECT count(*) FROM alert WHERE deal = $1 AND status = 'new'")
            .bind(&name)
            .fetch_one(&mut *tx)
            .await?;
    let notes: (i64,) = sqlx::query_as("SELECT count(*) FROM deal_note WHERE deal = $1")
        .bind(&name)
        .fetch_one(&mut *tx)
        .await?;
    tx.commit().await?;

    let changed = since.len();
    Ok(Json(json!({
        "deal": deal.0, "stage": deal.1, "sic": deal.2, "sponsor": deal.3, "legal_hold": deal.4,
        "ic": {
            "recorded": latest.is_some(),
            "latest": latest.map(decision_json),
            "dissents": dissents,
            "changed_since_ic": changed,
            "changed_documents": since.iter().take(5).cloned().collect::<Vec<_>>(),
        },
        "documents": { "count": docs.len(), "latest": latest_docs },
        "dd": { "total": dd_total, "closed": dd_closed, "pct_complete": pct },
        "open_alerts": open_alerts.0,
        "notes": notes.0,
    })))
}
