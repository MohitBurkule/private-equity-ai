//! Port of the admin reads that take ADMIN_TOKEN (app/main.py admin_list_keys and admin_document_access). The token is
//! read from the environment per request, as FastAPI does. The write routes stay on FastAPI and are relayed.

use crate::audit::log_event;
use crate::auth::hash_key;
use crate::error::ApiError;
use crate::AppState;
use axum::{
    body::Bytes,
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

/// Python acl.ROLES, in order.
const ROLES: [&str; 8] = [
    "admin",
    "partner",
    "vp",
    "associate",
    "analyst",
    "compliance",
    "ir",
    "viewer",
];

/// The tuple repr FastAPI puts in the role error.
fn roles_repr() -> String {
    format!(
        "({})",
        ROLES
            .iter()
            .map(|r| format!("'{r}'"))
            .collect::<Vec<_>>()
            .join(", ")
    )
}

/// A new key: "pe_" plus 32 random bytes, URL-safe base64 without padding (Python token_urlsafe(32)).
fn new_key() -> String {
    use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
    use rand::RngCore;
    let mut bytes = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut bytes);
    format!("pe_{}", URL_SAFE_NO_PAD.encode(bytes))
}

/// Python format_deals: sorted unique names; an empty list stores "", not null.
fn format_deals(deals: Option<&[String]>) -> Option<String> {
    deals.map(|d| {
        let set: BTreeSet<&str> = d
            .iter()
            .map(|x| x.trim())
            .filter(|x| !x.is_empty())
            .collect();
        set.into_iter().collect::<Vec<_>>().join(",")
    })
}

/// Python format_deal_roles: each name and role is checked, and an override may only name a deal in scope.
fn format_deal_roles(
    roles: Option<&BTreeMap<String, String>>,
    deals: Option<&[String]>,
) -> Result<Option<String>, ApiError> {
    let Some(roles) = roles.filter(|r| !r.is_empty()) else {
        return Ok(None);
    };
    for (deal, role) in roles {
        if deal.contains(':') || deal.contains(',') || deal.trim().is_empty() {
            return Err(ApiError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                format!("deal name '{deal}' cannot contain ':' or ','"),
            ));
        }
        if !ROLES.contains(&role.as_str()) {
            return Err(ApiError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                format!("role '{role}' must be one of {}", roles_repr()),
            ));
        }
        if let Some(d) = deals {
            if !d.iter().any(|x| x == deal) {
                return Err(ApiError::new(
                    StatusCode::UNPROCESSABLE_ENTITY,
                    format!("deal '{deal}' is outside the key's deal scope"),
                ));
            }
        }
    }
    Ok(Some(
        roles
            .iter()
            .map(|(d, r)| format!("{d}:{r}"))
            .collect::<Vec<_>>()
            .join(","),
    ))
}

/// Python format_groups: lower-cased, split on commas, unique and sorted; nothing left means null.
fn format_groups(groups: Option<&[String]>) -> Option<String> {
    let groups = groups.filter(|g| !g.is_empty())?;
    let set: BTreeSet<String> = groups
        .join(",")
        .split(',')
        .map(|g| g.trim().to_lowercase())
        .filter(|g| !g.is_empty())
        .collect();
    (!set.is_empty()).then(|| set.into_iter().collect::<Vec<_>>().join(","))
}

/// The JSON body of POST /admin/tenants/{id}/keys. Every field is optional, and a missing body means all defaults.
#[derive(serde::Deserialize, Default)]
pub struct KeyBody {
    role: Option<String>,
    deals: Option<Vec<String>>,
    deal_roles: Option<BTreeMap<String, String>>,
    identity: Option<String>,
    groups: Option<Vec<String>>,
}

/// POST /admin/tenants/{tenant_id}/keys: issue a key (201). The plain key is shown once; only its hash is stored.
pub async fn add_key(
    State(s): State<AppState>,
    headers: HeaderMap,
    Path(tenant): Path<String>,
    body: Bytes,
) -> Result<(StatusCode, Json<Value>), ApiError> {
    if !admin_token_ok(&headers) {
        return Err(forbidden());
    }
    let mut tx = tenant_tx(&s, &tenant).await?;
    let body: KeyBody = if body.is_empty() {
        KeyBody::default()
    } else {
        serde_json::from_slice(&body)
            .map_err(|e| ApiError::new(StatusCode::UNPROCESSABLE_ENTITY, e.to_string()))?
    };
    let role = body.role.clone().unwrap_or_else(|| "analyst".into());
    if !ROLES.contains(&role.as_str()) {
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("role must be one of {}", roles_repr()),
        ));
    }
    let deals = format_deals(body.deals.as_deref());
    let deal_roles = format_deal_roles(body.deal_roles.as_ref(), body.deals.as_deref())?;
    let identity = body
        .identity
        .as_deref()
        .filter(|i| !i.is_empty())
        .map(str::to_lowercase);
    let groups = format_groups(body.groups.as_deref());
    let key = new_key();
    let hash = hash_key(&key);
    sqlx::query(
        "INSERT INTO api_key (key_hash, tenant_id, revoked, role, deals, deal_roles, identity, groups) \
         VALUES ($1, $2, false, $3, $4, $5, $6, $7)",
    )
    .bind(&hash)
    .bind(&tenant)
    .bind(&role)
    .bind(deals)
    .bind(deal_roles)
    .bind(identity)
    .bind(groups)
    .execute(&mut *tx)
    .await?;
    tx.commit().await?;
    Ok((
        StatusCode::CREATED,
        Json(json!({
            "key_id": &hash[..12],
            "role": role,
            "deals": body.deals,
            "deal_roles": body.deal_roles,
            "api_key": key,
            "note": "store this key now; it is not shown again",
        })),
    ))
}

#[derive(serde::Deserialize)]
pub struct TenantBody {
    name: String,
}

/// POST /admin/tenants: a new tenant with one admin key (201). The tenant id is 8 random bytes in hex.
pub async fn create_tenant(
    State(s): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<TenantBody>,
) -> Result<(StatusCode, Json<Value>), ApiError> {
    if !admin_token_ok(&headers) {
        return Err(forbidden());
    }
    use rand::RngCore;
    let mut id_bytes = [0u8; 8];
    rand::thread_rng().fill_bytes(&mut id_bytes);
    let id = hex::encode(id_bytes);
    let key = new_key();
    let hash = hash_key(&key);
    let mut tx = s.pool.begin().await?;
    sqlx::query("INSERT INTO tenant (id, name) VALUES ($1, $2)")
        .bind(&id)
        .bind(&body.name)
        .execute(&mut *tx)
        .await?;
    sqlx::query(
        "INSERT INTO api_key (key_hash, tenant_id, revoked, role) VALUES ($1, $2, false, 'admin')",
    )
    .bind(&hash)
    .bind(&id)
    .execute(&mut *tx)
    .await?;
    tx.commit().await?;
    Ok((
        StatusCode::CREATED,
        Json(json!({
            "tenant_id": id,
            "api_key": key,
            "key_id": &hash[..12],
            "note": "store this key now; it is not shown again",
        })),
    ))
}

/// Test-only override (GRAPH_BASE_URL, honoured solely under PE_TEST_MODE=1), as in connectors/graph.py.
pub fn graph_override() -> Option<String> {
    if std::env::var("PE_TEST_MODE").ok().as_deref() != Some("1") {
        return None;
    }
    std::env::var("GRAPH_BASE_URL")
        .ok()
        .filter(|u| !u.is_empty())
}

/// Graph base URL: the test override when active, else production Graph.
fn graph_base() -> String {
    graph_override().unwrap_or_else(|| "https://graph.microsoft.com/v1.0".to_string())
}

/// Percent-encodes everything but unreserved characters (Python quote(email, safe='')).
fn quote(raw: &str) -> String {
    raw.bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                (b as char).to_string()
            }
            _ => format!("%{b:02X}"),
        })
        .collect()
}

/// Port of connectors/graph.py DirectoryGroups.member_of: the directory group ids a person is in, lower-cased,
/// sorted. Follows @odata.nextLink. Any transport or parse failure is a 502, as the Python ConnectorError is.
async fn member_of(
    http: &reqwest::Client,
    token: &str,
    email: &str,
) -> Result<Vec<String>, ApiError> {
    let bad = |what: &str| ApiError::new(StatusCode::BAD_GATEWAY, what.to_string());
    let mut url = format!(
        "{}/users/{}/memberOf?$select=id",
        graph_base(),
        quote(email)
    );
    let mut ids: BTreeSet<String> = BTreeSet::new();
    loop {
        let resp = http
            .get(&url)
            .bearer_auth(token)
            .header("Accept", "application/json")
            .send()
            .await
            .map_err(|_| bad("directory request failed"))?;
        if !resp.status().is_success() {
            return Err(bad("directory request failed"));
        }
        let page: Value = resp
            .json()
            .await
            .map_err(|_| bad("non-JSON response from directory"))?;
        for g in page
            .get("value")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            if let Some(id) = g
                .get("id")
                .and_then(Value::as_str)
                .filter(|i| !i.is_empty())
            {
                ids.insert(id.to_lowercase());
            }
        }
        match page
            .get("@odata.nextLink")
            .and_then(Value::as_str)
            .filter(|u| !u.is_empty())
        {
            Some(next) => url = next.to_string(),
            None => break,
        }
    }
    Ok(ids.into_iter().collect())
}

#[derive(serde::Deserialize)]
pub struct GroupSyncBody {
    token: String,
}

/// POST /admin/tenants/{tenant_id}/keys/{kid}/groups/sync: set a key's groups from its person's directory
/// memberships. The token is used once for the lookup and never stored.
pub async fn sync_key_groups(
    State(s): State<AppState>,
    headers: HeaderMap,
    Path((tenant, kid)): Path<(String, String)>,
    Json(body): Json<GroupSyncBody>,
) -> Result<Json<Value>, ApiError> {
    if !admin_token_ok(&headers) {
        return Err(forbidden());
    }
    if body.token.is_empty() || body.token.len() > 4096 {
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "token must be 1 to 4096 characters",
        ));
    }
    let mut tx = s.pool.begin().await?;
    let rows: Vec<(String, bool, Option<String>)> = sqlx::query_as(
        "SELECT key_hash, revoked, identity FROM api_key WHERE tenant_id = $1 ORDER BY key_hash",
    )
    .bind(&tenant)
    .fetch_all(&mut *tx)
    .await?;
    let Some((hash, revoked, identity)) = rows
        .into_iter()
        .find(|(h, _, _)| h[..12.min(h.len())] == kid)
    else {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "key not found"));
    };
    if revoked {
        return Err(ApiError::new(StatusCode::NOT_FOUND, "key not found"));
    }
    let Some(identity) = identity.filter(|i| !i.is_empty()) else {
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "key has no identity to look up in the directory",
        ));
    };
    let groups = member_of(&s.http, &body.token, &identity).await?;
    sqlx::query("UPDATE api_key SET groups = $2 WHERE key_hash = $1")
        .bind(&hash)
        .bind(format_groups(Some(&groups)))
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    Ok(Json(json!({ "key_id": kid, "groups": groups })))
}
