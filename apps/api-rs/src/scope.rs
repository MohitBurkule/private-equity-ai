//! Access gate for writes. Visibility lives in visibility.rs.

use crate::auth::Principal;
use crate::error::ApiError;
use axum::http::StatusCode;

/// Matches `writer`: the key must carry the write capability somewhere.
pub fn require_writer(p: &Principal) -> Result<(), ApiError> {
    if !p.can_write_somewhere() {
        return Err(ApiError::new(StatusCode::FORBIDDEN, "role is read-only"));
    }
    Ok(())
}
