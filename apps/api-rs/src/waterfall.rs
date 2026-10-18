//! Port of POST /calc/waterfall (app/waterfall.py). Exit proceeds by class for a preferred cap table. A class converts
//! to common when that pays more than staying preferred, found by iterating until stable. Payouts add up to the exit.

use crate::auth::principal;
use crate::error::ApiError;
use crate::facts::Dec;
use crate::AppState;
use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    Json,
};
use rust_decimal::{Decimal, RoundingStrategy};
use serde::Deserialize;
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;

fn one() -> Dec {
    Dec(Decimal::ONE)
}

#[derive(Deserialize)]
pub struct PrefClassIn {
    name: String,
    shares: Dec,
    invested: Dec,
    #[serde(default = "one")]
    pref_multiple: Dec,
    #[serde(default = "one_rank")]
    rank: i64,
    #[serde(default)]
    participating: bool,
    cap_multiple: Option<Dec>,
}

fn one_rank() -> i64 {
    1
}

#[derive(Deserialize)]
pub struct WaterfallIn {
    exit_value: Dec,
    common_shares: Dec,
    classes: Vec<PrefClassIn>,
}

/// Payouts by name, in Python dict order: the classes as given, then common.
type Pay = Vec<(String, Decimal)>;

fn get(pay: &Pay, name: &str) -> Decimal {
    pay.iter()
        .find(|(n, _)| n == name)
        .map_or(Decimal::ZERO, |(_, v)| *v)
}

fn add_to(pay: &mut Pay, name: &str, v: Decimal) {
    if let Some(slot) = pay.iter_mut().find(|(n, _)| n == name) {
        slot.1 += v;
    }
}

fn distribute(
    exit: Decimal,
    classes: &[PrefClassIn],
    common: Decimal,
    conv: &BTreeSet<String>,
) -> Pay {
    let mut pay: Pay = classes
        .iter()
        .map(|c| (c.name.clone(), Decimal::ZERO))
        .collect();
    pay.push(("common".into(), Decimal::ZERO));
    let mut left = exit;
    let stay: Vec<&PrefClassIn> = classes.iter().filter(|c| !conv.contains(&c.name)).collect();
    let mut ranks: Vec<i64> = stay.iter().map(|c| c.rank).collect();
    ranks.sort_unstable();
    ranks.dedup();
    for rank in ranks {
        let tier: Vec<&PrefClassIn> = stay.iter().copied().filter(|c| c.rank == rank).collect();
        let owed: Vec<Decimal> = tier
            .iter()
            .map(|c| c.invested.0 * c.pref_multiple.0)
            .collect();
        let total: Decimal = owed.iter().fold(Decimal::ZERO, |acc, o| acc + o);
        let paid = left.min(total);
        for (c, o) in tier.iter().zip(&owed) {
            let add = if total.is_zero() {
                Decimal::ZERO
            } else {
                paid * o / total
            };
            add_to(&mut pay, &c.name, add);
        }
        left -= paid;
    }
    // Residual: common, converted classes and participating classes share by shares; caps bind iteratively.
    let mut sharers: Vec<(String, Decimal)> = vec![("common".into(), common)];
    for c in classes.iter().filter(|c| conv.contains(&c.name)) {
        sharers.push((c.name.clone(), c.shares.0));
    }
    for c in stay.iter().filter(|c| c.participating) {
        sharers.push((c.name.clone(), c.shares.0));
    }
    let caps: Vec<(String, Decimal)> = stay
        .iter()
        .filter(|c| c.participating)
        .filter_map(|c| {
            c.cap_multiple
                .as_ref()
                .map(|m| (c.name.clone(), m.0 * c.invested.0))
        })
        .collect();
    let cap_of = |n: &str| caps.iter().find(|(m, _)| m == n).map(|(_, v)| *v);
    while left > Decimal::ZERO && !sharers.is_empty() {
        let total_sh: Decimal = sharers.iter().fold(Decimal::ZERO, |acc, (_, s)| acc + s);
        if total_sh.is_zero() {
            break;
        }
        let share: Vec<(String, Decimal)> = sharers
            .iter()
            .map(|(n, s)| (n.clone(), left * s / total_sh))
            .collect();
        let capped: Vec<String> = share
            .iter()
            .filter(|(n, v)| cap_of(n).is_some_and(|cap| get(&pay, n) + *v > cap))
            .map(|(n, _)| n.clone())
            .collect();
        if capped.is_empty() {
            for (n, v) in &share {
                add_to(&mut pay, n, *v);
            }
            left = Decimal::ZERO;
            break;
        }
        for n in &capped {
            let give = cap_of(n).unwrap_or_default() - get(&pay, n);
            add_to(&mut pay, n, give);
            left -= give;
            sharers.retain(|(m, _)| m != n);
        }
    }
    if left > Decimal::ZERO {
        add_to(&mut pay, "common", left); // nobody else can take it (everyone capped): goes to common
    }
    pay
}

/// Python _to_cents: each figure to the cent, half to even; any rounding remainder goes to the largest recipient.
fn to_cents(pay: &Pay, exit: Decimal) -> Pay {
    let mut out: Pay = pay
        .iter()
        .map(|(n, v)| {
            let mut q = v.round_dp_with_strategy(2, RoundingStrategy::MidpointNearestEven);
            q.rescale(2);
            (n.clone(), q)
        })
        .collect();
    let total: Decimal = out.iter().fold(Decimal::ZERO, |acc, (_, v)| acc + v);
    let diff = exit - total;
    if !diff.is_zero() {
        // Python max() keeps the first of equal values.
        let mut top = 0;
        for (i, (_, v)) in out.iter().enumerate() {
            if *v > out[top].1 {
                top = i;
            }
        }
        out[top].1 += diff;
    }
    out
}

struct Outcome {
    payouts: Pay,
    converted: Vec<String>,
    status: &'static str,
    detail: &'static str,
}

/// Python waterfall(): toggle the one class whose switch gains most, until no switch gains.
fn waterfall(exit: Decimal, classes: &[PrefClassIn], common: Decimal) -> Result<Outcome, String> {
    let negative = exit < Decimal::ZERO
        || common < Decimal::ZERO
        || classes
            .iter()
            .any(|c| c.shares.0 < Decimal::ZERO || c.invested.0 < Decimal::ZERO);
    if negative {
        return Err("negative amounts are not allowed".into());
    }
    let names: BTreeSet<&str> = classes.iter().map(|c| c.name.as_str()).collect();
    if names.len() != classes.len() || classes.iter().any(|c| c.name == "common") {
        return Err("class names must be unique and not 'common'".into());
    }
    let mut conv: BTreeSet<String> = BTreeSet::new();
    for _ in 0..classes.len() * 2 + 2 {
        let pay = distribute(exit, classes, common, &conv);
        let mut best: Option<(&str, Decimal)> = None;
        for c in classes {
            let mut toggled = conv.clone();
            if !toggled.remove(&c.name) {
                toggled.insert(c.name.clone());
            }
            let gain =
                get(&distribute(exit, classes, common, &toggled), &c.name) - get(&pay, &c.name);
            // Python max() keeps the first class with the largest gain.
            if best.is_none_or(|(_, g)| gain > g) {
                best = Some((c.name.as_str(), gain));
            }
        }
        match best {
            Some((name, gain)) if gain > Decimal::ZERO => {
                let name = name.to_string();
                if !conv.remove(&name) {
                    conv.insert(name);
                }
            }
            _ => {
                return Ok(Outcome {
                    payouts: to_cents(&pay, exit),
                    converted: conv.into_iter().collect(),
                    status: "ok",
                    detail: "",
                })
            }
        }
    }
    let pay = distribute(exit, classes, common, &conv);
    Ok(Outcome {
        payouts: to_cents(&pay, exit),
        converted: conv.into_iter().collect(),
        status: "not_converged",
        detail: "conversion choices kept changing; check terms",
    })
}

pub async fn calc_waterfall(
    State(s): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<WaterfallIn>,
) -> Result<Json<Value>, ApiError> {
    let (_p, tx) = principal(&s, &headers).await?;
    tx.commit().await?;
    if body.classes.len() > 50 {
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "at most 50 classes",
        ));
    }
    let r = waterfall(body.exit_value.0, &body.classes, body.common_shares.0)
        .map_err(|e| ApiError::new(StatusCode::UNPROCESSABLE_ENTITY, e))?;
    let payouts: Map<String, Value> = r
        .payouts
        .iter()
        .map(|(n, v)| (n.clone(), json!(v.to_string())))
        .collect();
    Ok(Json(json!({
        "status": r.status,
        "detail": r.detail,
        "converted": r.converted,
        "payouts": payouts,
    })))
}
