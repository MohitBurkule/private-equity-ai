//! Port of GET /deals (app/main.py deal_list and _deal_out). Writes stay on FastAPI.
//! Same wall as the deal itself: a deal outside the key's scope, or an MNPI deal the key may not see, is left out.
//! Listing visible MNPI deals is audited (deal.mnpi_access via list), as in FastAPI.

use crate::audit::log_event;
use crate::auth::principal;
use crate::error::ApiError;
use crate::visibility::Visibility;
use crate::AppState;
use axum::{extract::State, http::HeaderMap, Json};
use serde_json::{json, Value};
use std::collections::HashMap;

/// deal row: name, stage, sic, sponsor, aliases, cik, lei, note, legal_hold, mnpi, updated_at.
type DealRow = (
    String,
    String,
    Option<String>,
    Option<String>,
    Option<String>,
    Option<String>,
    Option<String>,
    Option<String>,
    bool,
    bool,
    String,
);

/// Python _aliases_list: comma-separated, trimmed, empties dropped.
fn aliases_list(raw: Option<&str>) -> Vec<String> {
    raw.unwrap_or("")
        .split(',')
        .map(str::trim)
        .filter(|n| !n.is_empty())
        .map(str::to_string)
        .collect()
}

pub async fn list_deals(
    State(s): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let vis = Visibility::load(&mut tx, &p).await?;
    let rows: Vec<DealRow> = sqlx::query_as(
        "SELECT name, stage, sic, sponsor, aliases, cik, lei, note, legal_hold, mnpi, updated_at \
         FROM deal ORDER BY id",
    )
    .fetch_all(&mut *tx)
    .await?;
    let doc_counts: Vec<(String, i64)> =
        sqlx::query_as("SELECT deal, count(*) FROM document WHERE deal IS NOT NULL GROUP BY deal")
            .fetch_all(&mut *tx)
            .await?;
    let dd_rows: Vec<(String, String)> = sqlx::query_as("SELECT deal, status FROM dd_request")
        .fetch_all(&mut *tx)
        .await?;
    let docs: HashMap<String, i64> = doc_counts.into_iter().collect();
    // dd_total and dd_open: a request is closed unless its status is "open".
    let mut dd: HashMap<String, (i64, i64)> = HashMap::new();
    for (deal, status) in dd_rows {
        let e = dd.entry(deal).or_insert((0, 0));
        e.0 += 1;
        if status == "open" {
            e.1 += 1;
        }
    }

    let shown: Vec<DealRow> = rows
        .into_iter()
        .filter(|r| vis.deal_allows(Some(&r.0)))
        .collect();
    let mnpi_shown: Vec<String> = shown.iter().filter(|r| r.9).map(|r| r.0.clone()).collect();
    if !mnpi_shown.is_empty() {
        log_event(
            &mut tx,
            &p.tenant,
            &format!("key:{}", p.key_id),
            "deal.mnpi_access",
            &json!({ "deals": mnpi_shown, "via": "list" }),
        )
        .await?;
    }
    tx.commit().await?;

    let out: Vec<Value> = shown
        .into_iter()
        .map(|(name, stage, sic, sponsor, aliases, cik, lei, note, legal_hold, mnpi, updated_at)| {
            let (total, open) = dd.get(&name).copied().unwrap_or((0, 0));
            json!({
                "documents": docs.get(&name).copied().unwrap_or(0),
                "dd_total": total,
                "dd_open": open,
                "aliases": aliases_list(aliases.as_deref()),
                "name": name, "stage": stage, "sic": sic, "sponsor": sponsor, "cik": cik, "lei": lei,
                "note": note, "legal_hold": legal_hold, "mnpi": mnpi, "updated_at": updated_at,
            })
        })
        .collect();
    Ok(Json(Value::Array(out)))
}

#[cfg(test)]
mod tests {
    use super::aliases_list;

    #[test]
    fn aliases_split_trim_and_drop_empties() {
        assert_eq!(
            aliases_list(Some(" Acme , ,Beta Corp,")),
            vec!["Acme", "Beta Corp"]
        );
        assert!(aliases_list(None).is_empty());
        assert!(aliases_list(Some("")).is_empty());
    }
}
