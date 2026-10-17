//! Port of get_principal (app/main.py) and principal_for_key (app/auth.py). Tenant comes only from the key.

use crate::error::ApiError;
use axum::http::{HeaderMap, StatusCode};
use sha2::{Digest, Sha256};
use sqlx::{PgPool, Postgres, Transaction};

/// api_key row: tenant_id, role, revoked, deals, deal_roles, key_hash
type KeyRow = (String, String, bool, Option<String>, Option<String>, String);

#[derive(Debug, Clone)]
pub struct Principal {
    pub tenant: String,
    pub role: String,
    /// A key with a deal scope or per-deal roles. Those need the deal wall and ACL code, not yet ported.
    pub restricted: bool,
    /// First 12 chars of the key hash, as FastAPI names keys in the audit trail (key:<id>).
    pub key_id: String,
}

/// Roles with the "write" capability (app/acl.py CAPABILITIES).
pub const WRITE_ROLES: &[&str] = &["admin", "partner", "vp", "associate", "analyst"];

pub fn hash_key(key: &str) -> String {
    hex::encode(Sha256::digest(key.as_bytes()))
}

/// Returns the caller and an open transaction with the tenant bound (transaction-local, so pooled connections
/// cannot carry it to the next request).
pub async fn principal(
    pool: &PgPool,
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
    let mut tx = pool.begin().await?;
    let row: Option<KeyRow> = sqlx::query_as(
        "SELECT tenant_id, role, revoked, deals, deal_roles, key_hash FROM api_key WHERE key_hash = $1",
    )
    .bind(hash_key(token))
    .fetch_optional(&mut *tx)
    .await?;
    let Some((tenant, role, revoked, deals, deal_roles, kh)) = row else {
        return Err(unauth());
    };
    if revoked {
        return Err(unauth());
    }
    sqlx::query("SELECT set_config('app.tenant_id', $1, true)")
        .bind(&tenant)
        .execute(&mut *tx)
        .await?;
    let restricted = deals.is_some() || deal_roles.is_some_and(|d| !d.is_empty());
    let key_id = kh[..12].to_string();
    Ok((
        Principal {
            tenant,
            role,
            restricted,
            key_id,
        },
        tx,
    ))
}
