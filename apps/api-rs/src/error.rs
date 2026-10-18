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

    /// FastAPI's 422 for a path parameter that is not an integer.
    pub fn bad_int_path(name: &str, input: &str) -> Self {
        Self(
            StatusCode::UNPROCESSABLE_ENTITY,
            "validation error".into(),
            Some(json!([{
                "type": "int_parsing",
                "loc": ["path", name],
                "msg": "Input should be a valid integer, unable to parse string as an integer",
                "input": input,
            }])),
        )
    }
}

impl ApiError {
    /// FastAPI's 422 for an integer query parameter that is not an integer.
    pub fn query_int(name: &str, input: &str) -> Self {
        Self(
            StatusCode::UNPROCESSABLE_ENTITY,
            "validation error".into(),
            Some(json!([{
                "type": "int_parsing",
                "loc": ["query", name],
                "msg": "Input should be a valid integer, unable to parse string as an integer",
                "input": input,
            }])),
        )
    }

    /// FastAPI's 422 for an integer query parameter below its `ge` bound.
    pub fn query_below(name: &str, input: &str, ge: i64) -> Self {
        Self(
            StatusCode::UNPROCESSABLE_ENTITY,
            "validation error".into(),
            Some(json!([{
                "type": "greater_than_equal",
                "loc": ["query", name],
                "msg": format!("Input should be greater than or equal to {ge}"),
                "input": input,
                "ctx": {"ge": ge},
            }])),
        )
    }

    /// FastAPI's 422 for an integer query parameter above its `le` bound.
    pub fn query_above(name: &str, input: &str, le: i64) -> Self {
        Self(
            StatusCode::UNPROCESSABLE_ENTITY,
            "validation error".into(),
            Some(json!([{
                "type": "less_than_equal",
                "loc": ["query", name],
                "msg": format!("Input should be less than or equal to {le}"),
                "input": input,
                "ctx": {"le": le},
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
