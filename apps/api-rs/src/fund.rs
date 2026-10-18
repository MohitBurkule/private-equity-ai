//! Port of POST /calc/fund-metrics (app/fundmetrics.py fund_metrics and xirr). DPI, RVPI, TVPI and XIRR from dated
//! flows. Contributions are negative, distributions positive. IRR is XIRR on actual/365 days, and says why when the
//! flows cannot produce one, never a made-up number.

use crate::auth::principal;
use crate::error::ApiError;
use crate::facts::Dec;
use crate::AppState;
use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    Json,
};
use chrono::NaiveDate;
use rust_decimal::{Decimal, RoundingStrategy};
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize)]
pub struct FlowIn {
    date: String,
    amount: Dec,
}

#[derive(Deserialize)]
pub struct FundIn {
    flows: Vec<FlowIn>,
    nav: Dec,
    as_of: String,
}

/// The float a Decimal reads as: correctly rounded, as Python's float(Decimal) is.
fn as_f64(d: Decimal) -> f64 {
    d.to_string().parse().unwrap_or(f64::NAN)
}

fn xnpv(rate: f64, flows: &[(NaiveDate, f64)]) -> f64 {
    let t0 = flows[0].0;
    flows.iter().fold(0.0, |acc, (d, a)| {
        acc + a / (1.0 + rate).powf((d.signed_duration_since(t0).num_days() as f64) / 365.0)
    })
}

/// Python xirr(): bisection on the NPV, with the reason when there is no IRR.
fn xirr(mut flows: Vec<(NaiveDate, f64)>) -> (Option<f64>, &'static str) {
    flows.sort_by(|a, b| {
        a.0.cmp(&b.0)
            .then(a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal))
    });
    if flows.len() < 2 {
        return (None, "needs at least two dated flows");
    }
    if !(flows.iter().any(|(_, a)| *a < 0.0) && flows.iter().any(|(_, a)| *a > 0.0)) {
        return (
            None,
            "needs both a payment in and a payment out (or a positive NAV)",
        );
    }
    if flows[0].0 == flows[flows.len() - 1].0 {
        return (None, "all flows on one date");
    }
    let (mut lo, mut hi) = (-0.999999_f64, 1e6_f64);
    let mut f_lo = xnpv(lo, &flows);
    let f_hi = xnpv(hi, &flows);
    if f_lo * f_hi > 0.0 {
        return (None, "no rate found that makes the flows net to zero");
    }
    for _ in 0..300 {
        let mid = (lo + hi) / 2.0;
        let f_mid = xnpv(mid, &flows);
        if f_lo * f_mid <= 0.0 {
            hi = mid;
        } else {
            lo = mid;
            f_lo = f_mid;
        }
        if hi - lo < 1e-12 {
            break;
        }
    }
    (Some((lo + hi) / 2.0), "")
}

/// Python str(v.quantize(Decimal("0.0001"))).
fn four_dp(d: Decimal) -> String {
    let mut r = d.round_dp_with_strategy(4, RoundingStrategy::MidpointNearestEven);
    r.rescale(4);
    r.to_string()
}

struct Metrics {
    paid_in: Decimal,
    distributed: Decimal,
    dpi: Option<Decimal>,
    rvpi: Option<Decimal>,
    tvpi: Option<Decimal>,
    irr: Option<f64>,
    irr_note: &'static str,
}

fn fund_metrics(
    flows: &[(NaiveDate, Decimal)],
    nav: Decimal,
    as_of: NaiveDate,
) -> Result<Metrics, String> {
    if nav < Decimal::ZERO {
        return Err("nav cannot be negative".into());
    }
    if flows.iter().any(|(d, _)| *d > as_of) {
        return Err("a cash flow is dated after as_of".into());
    }
    // Python negates the sum; a zero sum prints as "0", never "-0".
    let outflows = flows
        .iter()
        .filter(|(_, a)| *a < Decimal::ZERO)
        .fold(Decimal::ZERO, |acc, (_, a)| acc + a);
    let paid_in = if outflows.is_zero() {
        Decimal::ZERO
    } else {
        -outflows
    };
    let distributed = flows
        .iter()
        .filter(|(_, a)| *a > Decimal::ZERO)
        .fold(Decimal::ZERO, |acc, (_, a)| acc + a);
    let has_paid = !paid_in.is_zero();
    let dpi = has_paid.then(|| distributed / paid_in);
    let rvpi = has_paid.then(|| nav / paid_in);
    let tvpi = has_paid.then(|| (distributed + nav) / paid_in);
    let mut series: Vec<(NaiveDate, f64)> = flows.iter().map(|(d, a)| (*d, as_f64(*a))).collect();
    if !nav.is_zero() {
        series.push((as_of, as_f64(nav)));
    }
    let (irr, irr_note) = xirr(series);
    Ok(Metrics {
        paid_in,
        distributed,
        dpi,
        rvpi,
        tvpi,
        irr,
        irr_note,
    })
}

pub async fn calc_fund_metrics(
    State(s): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<FundIn>,
) -> Result<Json<Value>, ApiError> {
    let (_p, tx) = principal(&s, &headers).await?;
    tx.commit().await?;
    if body.flows.len() > 5000 {
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "at most 5000 flows",
        ));
    }
    let bad_date = || ApiError::new(StatusCode::UNPROCESSABLE_ENTITY, "invalid date");
    let as_of = NaiveDate::parse_from_str(&body.as_of, "%Y-%m-%d").map_err(|_| bad_date())?;
    let flows: Vec<(NaiveDate, Decimal)> = body
        .flows
        .iter()
        .map(|f| {
            Ok((
                NaiveDate::parse_from_str(&f.date, "%Y-%m-%d").map_err(|_| bad_date())?,
                f.amount.0,
            ))
        })
        .collect::<Result<_, ApiError>>()?;
    let nav = body.nav.0;
    let m = fund_metrics(&flows, nav, as_of)
        .map_err(|e| ApiError::new(StatusCode::UNPROCESSABLE_ENTITY, e))?;
    let q = |v: Option<Decimal>| v.map(four_dp);
    Ok(Json(json!({
        "paid_in": m.paid_in.to_string(),
        "distributed": m.distributed.to_string(),
        "nav": nav.to_string(),
        "dpi": q(m.dpi),
        "rvpi": q(m.rvpi),
        "tvpi": q(m.tvpi),
        "irr": m.irr.map(|x| format!("{x:.6}").parse::<f64>().unwrap_or(x)),
        "irr_note": m.irr_note,
    })))
}
