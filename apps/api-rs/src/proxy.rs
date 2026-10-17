//! Upstream fallback for routes the Rust API has not ported (uploads, extraction, memo, ...).
//! Enabled by FASTAPI_UPSTREAM (e.g. http://127.0.0.1:8000). The request is forwarded as-is, so FastAPI does the
//! auth, tenancy and work; Rust only relays. Without the env var, unported routes return 404.

use crate::AppState;
use axum::{
    body::{to_bytes, Body},
    extract::{Request, State},
    http::{header, HeaderName, StatusCode},
    response::{IntoResponse, Response},
};

/// Largest request body relayed upstream (uploads of filings and decks can be big).
const MAX_BODY: usize = 256 * 1024 * 1024;

/// Hop-by-hop headers are per connection and must not be relayed.
fn hop_by_hop(name: &HeaderName) -> bool {
    matches!(
        name.as_str(),
        "connection"
            | "keep-alive"
            | "proxy-connection"
            | "transfer-encoding"
            | "te"
            | "trailer"
            | "upgrade"
            | "host"
    )
}

pub async fn forward(State(s): State<AppState>, req: Request) -> Response {
    let Some(base) = s.upstream.as_deref() else {
        return StatusCode::NOT_FOUND.into_response();
    };
    let (parts, body) = req.into_parts();
    let bytes = match to_bytes(body, MAX_BODY).await {
        Ok(b) => b,
        Err(_) => return StatusCode::PAYLOAD_TOO_LARGE.into_response(),
    };
    let path = parts
        .uri
        .path_and_query()
        .map(|p| p.as_str())
        .unwrap_or("/");
    let url = format!("{}{}", base.trim_end_matches('/'), path);
    let mut out = s.http.request(parts.method.clone(), url);
    for (name, value) in parts.headers.iter().filter(|(n, _)| !hop_by_hop(n)) {
        out = out.header(name, value);
    }
    let resp = match out.body(bytes).send().await {
        Ok(r) => r,
        Err(_) => return StatusCode::BAD_GATEWAY.into_response(),
    };
    let status = resp.status();
    let mut headers = axum::http::HeaderMap::new();
    for (name, value) in resp.headers().iter().filter(|(n, _)| !hop_by_hop(n)) {
        headers.append(name.clone(), value.clone());
    }
    let body = match resp.bytes().await {
        Ok(b) => b,
        Err(_) => return StatusCode::BAD_GATEWAY.into_response(),
    };
    let mut out_resp = Response::new(Body::from(body));
    *out_resp.status_mut() = status;
    *out_resp.headers_mut() = headers;
    out_resp.headers_mut().remove(header::TRANSFER_ENCODING);
    out_resp
}
