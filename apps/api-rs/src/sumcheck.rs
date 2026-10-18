//! Port of POST /calc/sumcheck (app/sumcheck.py sum_check). Pure arithmetic: a gap is reported with its exact amount,
//! never rounded away.

use crate::auth::principal;
use crate::error::ApiError;
use crate::facts::de_decimal;
use crate::AppState;
use axum::{extract::State, http::HeaderMap, Json};
use rust_decimal::Decimal;
use serde::Deserialize;
use serde_json::{json, Value};

/// One printed part, read the way pydantic reads a Decimal.
#[derive(Deserialize)]
struct Part(#[serde(deserialize_with = "de_decimal")] Decimal);

fn zero() -> Decimal {
    Decimal::ZERO
}

#[derive(Deserialize)]
pub struct SumCheckIn {
    parts: Vec<Part>,
    #[serde(deserialize_with = "de_decimal")]
    stated: Decimal,
    #[serde(default = "zero", deserialize_with = "de_decimal")]
    rounding_unit: Decimal,
}

pub async fn calc_sumcheck(
    State(s): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<SumCheckIn>,
) -> Result<Json<Value>, ApiError> {
    let (_p, tx) = principal(&s, &headers).await?;
    tx.commit().await?;
    let parts: Vec<Decimal> = body.parts.into_iter().map(|p| p.0).collect();
    let computed = parts.iter().fold(Decimal::ZERO, |acc, p| acc + p);
    let diff = body.stated - computed;
    let (status, detail) = if diff.is_zero() {
        ("ties", "")
    } else if body.rounding_unit > Decimal::ZERO
        && diff.abs() <= body.rounding_unit * Decimal::from(parts.len())
    {
        ("rounding", "within rounding of the printed parts")
    } else {
        ("gap", "parts do not add up to the stated total")
    };
    Ok(Json(json!({
        "status": status,
        "computed": computed.to_string(),
        "stated": body.stated.to_string(),
        "difference": diff.to_string(),
        "detail": detail,
    })))
}
