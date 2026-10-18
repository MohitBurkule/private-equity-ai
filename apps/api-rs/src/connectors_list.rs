//! Port of GET /connectors (app/connectors/registry.py status and connection_health). The catalogue and the set of
//! built connectors come from src/connector_catalog.json, a snapshot of app.connectors.registry. Regenerate it in the
//! same PR whenever a connector is added, built or renamed; `make parity` compares this route with FastAPI.
//! Each entry's state is computed from the tenant's saved connections and from the OAuth environment, as in Python.

use crate::auth::principal;
use crate::error::ApiError;
use crate::AppState;
use axum::{extract::State, http::HeaderMap, Json};
use serde::Deserialize;
use serde_json::{json, Map, Value};
use std::collections::HashMap;

#[derive(Deserialize)]
struct Snapshot {
    catalog: Vec<CatalogEntry>,
    implemented: Vec<String>,
    imports: Vec<String>,
}

#[derive(Deserialize)]
struct CatalogEntry {
    name: String,
    label: String,
    category: String,
    auth: String,
}

fn snapshot() -> Snapshot {
    serde_json::from_str(include_str!("connector_catalog.json"))
        .expect("connector_catalog.json is valid JSON")
}

/// Python _oauth_ready: all four OAuth settings present and both endpoints https.
fn oauth_ready(name: &str) -> bool {
    let p = format!("OAUTH_{}_", name.to_uppercase().replace('-', "_"));
    let get = |k: &str| std::env::var(format!("{p}{k}")).unwrap_or_default();
    let (id, secret, auth_url, token_url) = (
        get("CLIENT_ID"),
        get("CLIENT_SECRET"),
        get("AUTH_URL"),
        get("TOKEN_URL"),
    );
    if [&id, &secret, &auth_url, &token_url]
        .iter()
        .any(|v| v.is_empty())
    {
        return false;
    }
    auth_url.starts_with("https://") && token_url.starts_with("https://")
}

/// Python connection_health(): never run, ok, or error with the stored message.
fn health(last_run: Option<&str>, last_status: Option<&str>) -> Value {
    match last_run {
        None => json!({"health": "never_run", "last_run": null, "last_status": null}),
        Some(run) => {
            let state = if last_status.unwrap_or("").starts_with("ok") {
                "ok"
            } else {
                "error"
            };
            json!({"health": state, "last_run": run, "last_status": last_status.unwrap_or("")})
        }
    }
}

pub async fn list_connectors(
    State(s): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    let (_p, mut tx) = principal(&s, &headers).await?;
    // Python keeps the last row per connector, in query order.
    let rows: Vec<(String, Option<String>, Option<String>)> =
        sqlx::query_as("SELECT connector, last_run, last_status FROM connection ORDER BY id")
            .fetch_all(&mut *tx)
            .await?;
    tx.commit().await?;
    let mut saved: HashMap<String, (Option<String>, Option<String>)> = HashMap::new();
    for (connector, last_run, last_status) in rows {
        saved.insert(connector, (last_run, last_status));
    }

    let snap = snapshot();
    let out: Vec<Value> = snap
        .catalog
        .iter()
        .map(|c| {
            let planned = !snap.implemented.contains(&c.name) && !snap.imports.contains(&c.name);
            let auth = c.auth.to_lowercase();
            let (state, detail) = if planned {
                ("stubbed", "not built yet".to_string())
            } else if saved.contains_key(&c.name) {
                ("connected", "saved connection".to_string())
            } else if snap.imports.contains(&c.name) || auth.starts_with("none") {
                ("connected", "no key needed".to_string())
            } else if auth.starts_with("oauth") && !oauth_ready(&c.name) {
                (
                    "needs_key",
                    format!(
                        "set OAUTH_{}_CLIENT_ID, _CLIENT_SECRET, _AUTH_URL, _TOKEN_URL",
                        c.name.to_uppercase().replace('-', "_")
                    ),
                )
            } else {
                ("needs_key", "add a key when you import".to_string())
            };
            let mut entry = Map::new();
            entry.insert("name".into(), json!(c.name));
            entry.insert("label".into(), json!(c.label));
            entry.insert("category".into(), json!(c.category));
            entry.insert("auth".into(), json!(c.auth));
            entry.insert(
                "status".into(),
                json!(if planned { "planned" } else { "live" }),
            );
            entry.insert("state".into(), json!(state));
            entry.insert("detail".into(), json!(detail));
            if let Some((last_run, last_status)) = saved.get(&c.name) {
                if let Value::Object(h) = health(last_run.as_deref(), last_status.as_deref()) {
                    entry.extend(h);
                }
            }
            Value::Object(entry)
        })
        .collect();
    Ok(Json(Value::Array(out)))
}
