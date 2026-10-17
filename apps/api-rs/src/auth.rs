//! Port of get_principal (app/main.py), principal_for_key and the grant helpers (app/auth.py, app/acl.py).
//! Tenant comes only from the key.

use crate::error::ApiError;
use crate::AppState;
use axum::http::{HeaderMap, StatusCode};
use sha2::{Digest, Sha256};
use sqlx::{Postgres, Transaction};
use std::collections::HashSet;

/// Roles with the "write" capability (app/acl.py CAPABILITIES).
pub const WRITE_ROLES: &[&str] = &["admin", "partner", "vp", "associate", "analyst"];

/// api_key row: tenant_id, role, revoked, deals, deal_roles, key_hash, identity, groups
type KeyRow = (
    String,
    String,
    bool,
    Option<String>,
    Option<String>,
    String,
    Option<String>,
    Option<String>,
);

#[derive(Debug, Clone)]
pub struct Principal {
    pub tenant: String,
    pub role: String,
    /// Deal names this key is scoped to; None means unscoped inside the tenant.
    pub deals: Option<HashSet<String>>,
    /// (deal, role) overrides, e.g. a viewer key that is partner on one deal.
    pub deal_roles: Vec<(String, String)>,
    /// First 12 chars of the key hash, as FastAPI names keys (key:<id>).
    pub key_id: String,
    pub identity: Option<String>,
    pub groups: Vec<String>,
}

impl Principal {
    pub fn deal_scope_has(&self, deal: &str) -> bool {
        self.deals.as_ref().is_some_and(|d| d.contains(deal))
    }

    /// What this principal matches in a source's access list (app/acl.py principal_grants).
    pub fn grants(&self) -> HashSet<String> {
        let mut out: HashSet<String> = self.groups.iter().map(|g| format!("group:{g}")).collect();
        if let Some(id) = &self.identity {
            out.insert(id.to_lowercase());
        }
        out
    }

    /// Mirrors `can_anywhere("write")`: the role, or any per-deal role, carries the write capability.
    pub fn can_write_somewhere(&self) -> bool {
        WRITE_ROLES.contains(&self.role.as_str())
            || self
                .deal_roles
                .iter()
                .any(|(_, r)| WRITE_ROLES.contains(&r.as_str()))
    }
}

pub fn hash_key(key: &str) -> String {
    hex::encode(Sha256::digest(key.as_bytes()))
}

/// Accepts the same forms as acl.py: comma lists, trimmed, empty entries dropped.
fn parse_list(raw: &str) -> Vec<String> {
    raw.split(',')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .collect()
}

/// Returns the caller and an open transaction with the tenant bound (transaction-local, so pooled connections
/// cannot carry it to the next request).
pub async fn principal(
    s: &AppState,
    headers: &HeaderMap,
) -> Result<(Principal, Transaction<'static, Postgres>), ApiError> {
    let unauth = || ApiError::new(StatusCode::UNAUTHORIZED, "invalid token");
    let raw = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .ok_or_else(|| ApiError::new(StatusCode::UNAUTHORIZED, "missing bearer token"))?;
    let token = raw
        .get(..7)
        .filter(|p| p.eq_ignore_ascii_case("bearer "))
        .map(|_| raw[7..].trim())
        .ok_or_else(|| ApiError::new(StatusCode::UNAUTHORIZED, "missing bearer token"))?;
    // A JWT has two dots and goes to OIDC in FastAPI. Not ported yet.
    if token.matches('.').count() == 2 {
        return Err(ApiError::new(
            StatusCode::NOT_IMPLEMENTED,
            "OIDC tokens not ported to the Rust API yet",
        ));
    }
    let mut tx = s.pool.begin().await?;
    let row: Option<KeyRow> = sqlx::query_as(
        "SELECT tenant_id, role, revoked, deals, deal_roles, key_hash, identity, groups FROM api_key WHERE key_hash = $1",
    )
    .bind(hash_key(token))
    .fetch_optional(&mut *tx)
    .await?;
    let Some((tenant, role, revoked, deals, deal_roles, kh, identity, groups)) = row else {
        return Err(unauth());
    };
    // Same order as get_principal: the limit applies after the key is accepted, before tenant binding.
    if revoked {
        return Err(unauth());
    }
    if !s.limiter.allow(&tenant) {
        return Err(ApiError::new(
            StatusCode::TOO_MANY_REQUESTS,
            "rate limit exceeded",
        ));
    }
    sqlx::query("SELECT set_config('app.tenant_id', $1, true)")
        .bind(&tenant)
        .execute(&mut *tx)
        .await?;
    let deal_roles = deal_roles
        .as_deref()
        .unwrap_or("")
        .split(',')
        .filter_map(|pair| pair.split_once(':'))
        .map(|(d, r)| (d.to_string(), r.to_string()))
        .collect();
    let principal = Principal {
        tenant,
        role,
        deals: deals.map(|d| parse_list(&d).into_iter().collect()),
        deal_roles,
        key_id: kh[..12].to_string(),
        identity: identity.map(|i| i.to_lowercase()),
        groups: {
            let mut g: Vec<String> = parse_list(groups.as_deref().unwrap_or(""))
                .iter()
                .map(|g| g.to_lowercase())
                .collect();
            g.sort();
            g.dedup();
            g
        },
    };
    Ok((principal, tx))
}
