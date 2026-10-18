//! Port of the trading-comps read used by GET /memo (app/comps.py `run`, with the memo's arguments: one metric,
//! revenue, no FX conversion, no period overrides). A multiple is computed only when EV and revenue exist, share a
//! unit and the denominator is positive; otherwise the peer carries the reason. Statistics skip those peers.

use crate::error::ApiError;
use crate::facts::stored;
use crate::visibility::Visibility;
use rust_decimal::prelude::ToPrimitive;
use rust_decimal::{Decimal, RoundingStrategy};
use sqlx::{Postgres, Transaction};

/// Python comps.MIN_PEERS: fewer usable multiples give no implied range.
pub const MIN_PEERS: usize = 3;

/// fact_source row: document_id, page, quote, kind, section, heading, anchor.
type SourceRow = (
    String,
    i32,
    String,
    String,
    Option<String>,
    Option<String>,
    Option<String>,
);

/// One citation of a fact: the same fields FastAPI's FactSource carries.
#[derive(Clone)]
pub struct SourceRec {
    pub doc_id: String,
    pub page: i32,
    pub section: Option<String>,
    pub heading: Option<String>,
    pub kind: String,
    pub anchor: Option<String>,
    pub quote: String,
}

/// A verified fact the caller may see, with its sources in id order.
#[derive(Clone)]
pub struct FactRec {
    pub value: Decimal,
    pub unit: String,
    pub sources: Vec<SourceRec>,
}

pub struct Peer {
    pub entity: String,
    pub ev: Option<FactRec>,
    pub rev: Option<FactRec>,
    pub multiple: Option<Decimal>,
    /// Why there is no multiple (python `nm`); None when there is one.
    pub nm: Option<String>,
}

pub struct Implied {
    pub target: Option<FactRec>,
    pub low: Option<Decimal>,
    pub mid: Option<Decimal>,
    pub high: Option<Decimal>,
    pub note: String,
}

pub struct Comps {
    pub period: String,
    pub peers: Vec<Peer>,
    pub n: usize,
    pub median: Option<Decimal>,
    pub implied: Implied,
}

/// Python `_find`: the latest visible verified fact for entity, metric and period.
pub async fn find_fact(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    entity: &str,
    metric: &str,
    period: &str,
) -> Result<Option<FactRec>, ApiError> {
    let rows: Vec<(i32, Decimal, String)> = sqlx::query_as(
        "SELECT id, value, unit FROM fact WHERE entity = $1 AND metric = $2 AND period = $3 \
         AND status = 'verified' ORDER BY id DESC",
    )
    .bind(entity)
    .bind(metric)
    .bind(period)
    .fetch_all(&mut **tx)
    .await?;
    for (id, value, unit) in rows {
        let value = stored(value);
        let srcs: Vec<SourceRow> = sqlx::query_as(
            "SELECT document_id, page, quote, kind, section, heading, anchor FROM fact_source \
                 WHERE fact_id = $1 ORDER BY id",
        )
        .bind(id)
        .fetch_all(&mut **tx)
        .await?;
        let sources: Vec<SourceRec> = srcs
            .into_iter()
            .map(
                |(doc_id, page, quote, kind, section, heading, anchor)| SourceRec {
                    doc_id,
                    page,
                    section,
                    heading,
                    kind,
                    anchor,
                    quote,
                },
            )
            .collect();
        let ids: Vec<&str> = sources.iter().map(|s| s.doc_id.as_str()).collect();
        if vis.fact_visible(&ids) {
            return Ok(Some(FactRec {
                value,
                unit,
                sources,
            }));
        }
    }
    Ok(None)
}

/// Python `multiple`: (multiple, reason). The quotient is normalised, which matches Python's exact-division exponent
/// for the whole-unit figures the comps read.
fn multiple(ev: Decimal, denom: Decimal) -> (Option<Decimal>, String) {
    if denom <= Decimal::ZERO {
        return (None, "denominator not positive".into());
    }
    if ev <= Decimal::ZERO {
        return (None, "enterprise value not positive".into());
    }
    ((ev / denom).normalize().into(), String::new())
}

/// Python `_quantile`: linear interpolation between closest ranks.
fn quantile(vals: &[Decimal], p: Decimal) -> Decimal {
    let mut s = vals.to_vec();
    s.sort();
    let pos = Decimal::from(s.len() as i64 - 1) * p;
    let lo = pos.trunc().to_usize().unwrap_or(0);
    let hi = (lo + 1).min(s.len() - 1);
    let frac = pos - Decimal::from(lo as i64);
    let diff = s[hi] - s[lo];
    // Python keeps the exponent of each operand: the step has the scale of diff plus frac, and the sum keeps the
    // larger scale of the two. Decimal's own arithmetic drops trailing zeros, so the scale is set here.
    let step_scale = diff.scale() + p.scale();
    let mut out = s[lo] + diff * frac;
    out.rescale(s[lo].scale().max(step_scale));
    out
}

/// Python comps.run for the memo: peers are every entity except the target, the metric is revenue.
pub async fn run_revenue(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    target: &str,
    entities: &[String],
    period: &str,
) -> Result<Comps, ApiError> {
    let mut peers = Vec::new();
    for entity in entities.iter().filter(|e| e.as_str() != target) {
        let ev = find_fact(tx, vis, entity, "enterprise_value", period).await?;
        let rev = find_fact(tx, vis, entity, "revenue", period).await?;
        let mut peer = Peer {
            entity: entity.clone(),
            ev: None,
            rev: None,
            multiple: None,
            nm: None,
        };
        match (ev, rev) {
            (None, _) => peer.nm = Some("no enterprise value fact".into()),
            (Some(ev), None) => {
                peer.nm = Some(format!("no revenue fact for {period}"));
                peer.ev = Some(ev);
            }
            (Some(ev), Some(rev)) => {
                if ev.unit != rev.unit {
                    peer.nm = Some(format!("unit mismatch {} vs {}", ev.unit, rev.unit));
                } else {
                    match multiple(ev.value, rev.value) {
                        (Some(m), _) => peer.multiple = Some(m),
                        (None, reason) => peer.nm = Some(reason),
                    }
                }
                peer.ev = Some(ev);
                peer.rev = Some(rev);
            }
        }
        peers.push(peer);
    }

    let vals: Vec<Decimal> = peers.iter().filter_map(|p| p.multiple).collect();
    let n = vals.len();
    let (q1, median, q3) = if n == 0 {
        (None, None, None)
    } else {
        (
            Some(quantile(&vals, Decimal::new(25, 2))),
            Some(quantile(&vals, Decimal::new(5, 1))),
            Some(quantile(&vals, Decimal::new(75, 2))),
        )
    };

    let implied = match find_fact(tx, vis, target, "revenue", period).await? {
        None => Implied {
            target: None,
            low: None,
            mid: None,
            high: None,
            note: format!("no revenue fact for {target}"),
        },
        Some(t) => {
            let tv = t.value;
            let (low, mid, high, note) = if tv <= Decimal::ZERO {
                (None, None, None, "target metric not positive".to_string())
            } else if n < MIN_PEERS {
                (
                    None,
                    None,
                    None,
                    format!("only {n} usable multiples, need {MIN_PEERS}"),
                )
            } else {
                (
                    q1.map(|q| tv * q),
                    median.map(|m| tv * m),
                    q3.map(|q| tv * q),
                    String::new(),
                )
            };
            Implied {
                target: Some(t),
                low,
                mid,
                high,
                note,
            }
        }
    };

    Ok(Comps {
        period: period.into(),
        peers,
        n,
        median,
        implied,
    })
}

/// Two-decimal figure with half-even rounding, as Python's `Decimal.quantize(Decimal("0.01"))` in comps.run.
pub fn quantize_multiple(d: Decimal) -> String {
    let mut q = d.round_dp_with_strategy(2, RoundingStrategy::MidpointNearestEven);
    q.rescale(2);
    q.to_string()
}
