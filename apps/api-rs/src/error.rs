//! Errors shaped like FastAPI's: {"detail": "..."} with the same status codes, or, for a request that fails
//! validation, {"detail": [{"type", "loc", "msg", "input"}]} as FastAPI returns for a missing parameter.

use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::{json, Value};

#[derive(Debug)]
pub struct ApiError(pub StatusCode, pub String, pub Option<Value>);

impl ApiError {
    pub fn new(code: StatusCode, msg: impl Into<String>) -> Self {
        Self(code, msg.into(), None)
    }

    /// FastAPI's 422 for a required query parameter that was not sent.
    pub fn missing_query(name: &str) -> Self {
        Self(
            StatusCode::UNPROCESSABLE_ENTITY,
            "validation error".into(),
            Some(json!([{
                "type": "missing",
                "loc": ["query", name],
                "msg": "Field required",
                "input": null,
            }])),
        )
    }
}

impl From<sqlx::Error> for ApiError {
    fn from(e: sqlx::Error) -> Self {
        // Do not leak SQL text to clients; the cause belongs in server logs.
        eprintln!("db error: {e}");
        Self(
            StatusCode::INTERNAL_SERVER_ERROR,
            "internal error".into(),
            None,
        )
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let detail = self.2.unwrap_or_else(|| json!(self.1));
        (self.0, Json(json!({ "detail": detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::ApiError;

    #[test]
    fn missing_query_matches_fastapi_shape() {
        let e = ApiError::missing_query("since");
        assert_eq!(e.0.as_u16(), 422);
        assert_eq!(
            e.2.unwrap(),
            serde_json::json!([{"type": "missing", "loc": ["query", "since"], "msg": "Field required", "input": null}])
        );
    }
}
