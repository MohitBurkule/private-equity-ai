//! Access gates shared by routes. Until the deal wall and source ACL are ported, only unrestricted keys on tenants
//! without walls get through. Everything else refuses with 501 instead of guessing at visibility.

use crate::auth::{Principal, WRITE_ROLES};
use crate::error::ApiError;
use axum::http::StatusCode;
use sqlx::{Postgres, Transaction};

pub fn require_unrestricted(p: &Principal) -> Result<(), ApiError> {
    if p.restricted {
        return Err(ApiError::new(
            StatusCode::NOT_IMPLEMENTED,
            "deal-scoped keys not ported to the Rust API yet",
        ));
    }
    Ok(())
}

/// Matches `writer`: the key's role must carry the write capability.
pub fn require_writer(p: &Principal) -> Result<(), ApiError> {
    if !WRITE_ROLES.contains(&p.role.as_str()) {
        return Err(ApiError::new(StatusCode::FORBIDDEN, "role is read-only"));
    }
    Ok(())
}

/// MNPI deals or ACL-restricted sources would hide rows from unrestricted keys. Refuse rather than leak.
pub async fn ensure_no_walls(tx: &mut Transaction<'_, Postgres>) -> Result<(), ApiError> {
    let (walls,): (bool,) = sqlx::query_as(
        "SELECT EXISTS (SELECT 1 FROM deal WHERE mnpi) OR EXISTS (SELECT 1 FROM document_source WHERE acl IS NOT NULL)",
    )
    .fetch_one(&mut **tx)
    .await?;
    if walls {
        return Err(ApiError::new(
            StatusCode::NOT_IMPLEMENTED,
            "tenant has deal walls or ACLs; not ported yet",
        ));
    }
    Ok(())
}
