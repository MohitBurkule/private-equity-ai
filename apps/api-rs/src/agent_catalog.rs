//! Port of GET /agent/tools and GET /agent/workflows (app/agent.py registries). The catalogue is the registered tool and
//! workflow metadata, read from src/agent_catalog.json. That snapshot is dumped from the Python registries after
//! importing app.agent and app.opendata_tools (the same modules main.py imports). Regenerate it in the same PR whenever
//! a tool or workflow is added or changed; `make parity` compares both routes against FastAPI.

use crate::auth::principal;
use crate::error::ApiError;
use crate::AppState;
use axum::{extract::State, http::HeaderMap, Json};
use serde_json::Value;

fn catalog() -> Value {
    serde_json::from_str(include_str!("agent_catalog.json"))
        .expect("agent_catalog.json is valid JSON")
}

pub async fn agent_tools(
    State(s): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    let (_p, tx) = principal(&s, &headers).await?;
    tx.commit().await?;
    Ok(Json(catalog()["tools"].clone()))
}

pub async fn agent_workflows(
    State(s): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    let (_p, tx) = principal(&s, &headers).await?;
    tx.commit().await?;
    Ok(Json(catalog()["workflows"].clone()))
}
