//! Port of POST /calc/comps (app/comps.py `run`): trading comps or precedents from cited facts. Each peer's multiple
//! is EV over a denominator that is either a stored fact or a derived formula (EBITDA). A unit mismatch is converted at
//! the ECB rate and the rate is cited. Anything that cannot be computed says why; nothing is defaulted.

use crate::auth::principal;
use crate::citations::locator_label;
use crate::comps::{quantile, SourceRec, MIN_PEERS};
use crate::derived;
use crate::error::ApiError;
use crate::facts::stored;
use crate::fx;
use crate::visibility::Visibility;
use crate::AppState;
use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    Json,
};
use chrono::{NaiveDate, Utc};
use rust_decimal::Decimal;
use serde::Deserialize;
use serde_json::{json, Map, Value};
use sqlx::{Postgres, Transaction};

const EV_METRIC: &str = "enterprise_value";
/// Python comps.MAX_AS_OF_AGE_DAYS: a market figure older than this is flagged stale.
const MAX_AS_OF_AGE_DAYS: i64 = 7;

fn default_metrics() -> Vec<String> {
    vec!["revenue".into(), "ebitda".into()]
}

#[derive(Deserialize)]
pub struct CompsIn {
    target: String,
    peers: Vec<String>,
    period: String,
    #[serde(default = "default_metrics")]
    metrics: Vec<String>,
    target_period: Option<String>,
    ev_period: Option<String>,
}

/// A verified fact the caller may see, with the fields the comps output cites.
#[derive(Clone)]
struct CFact {
    id: i32,
    value: Decimal,
    unit: String,
    period: String,
    as_of: Option<String>,
    sources: Vec<SourceRec>,
}

/// A denominator: a stored fact, or a derived formula with its component fact ids.
struct Denom {
    value: Decimal,
    unit: String,
    fact: Option<CFact>,
    formula: Option<(String, Vec<i32>)>,
}

struct Peer {
    entity: String,
    multiples: Vec<(String, Option<Decimal>)>,
    nm: Map<String, Value>,
    facts: Map<String, Value>,
    fx: Map<String, Value>,
    derived: Map<String, Value>,
    cells: Map<String, Value>,
    stale: Vec<String>,
}

/// Python stats(): summary of the usable multiples. Every field is None when there are none.
struct St {
    n: usize,
    low: Option<Decimal>,
    q1: Option<Decimal>,
    median: Option<Decimal>,
    mean: Option<Decimal>,
    q3: Option<Decimal>,
    high: Option<Decimal>,
}

type SourceRow = (
    String,
    i32,
    String,
    String,
    Option<String>,
    Option<String>,
    Option<String>,
);

/// Python Decimal division for these figures: an exact quotient keeps the larger of its own digits and the ideal
/// exponent (scale of a minus scale of b); an inexact one keeps the 28 significant digits Decimal gives.
fn py_div(a: Decimal, b: Decimal) -> Decimal {
    let q = a / b;
    if q * b != a {
        return q;
    }
    let needed = q.normalize().scale() as i64;
    let ideal = a.scale() as i64 - b.scale() as i64;
    let mut r = q;
    r.rescale(needed.max(ideal).max(0) as u32);
    r
}

/// Python multiple(): (multiple, reason). Denominator is checked first, as in comps.multiple.
fn multiple(ev: Decimal, denom: Decimal) -> (Option<Decimal>, Option<String>) {
    if denom <= Decimal::ZERO {
        return (None, Some("denominator not positive".into()));
    }
    if ev <= Decimal::ZERO {
        return (None, Some("enterprise value not positive".into()));
    }
    (Some(py_div(ev, denom)), None)
}

/// Python stats(): first minimum and first maximum, as Python's min() and max() return them.
fn stats(vals: &[Decimal]) -> St {
    if vals.is_empty() {
        return St {
            n: 0,
            low: None,
            q1: None,
            median: None,
            mean: None,
            q3: None,
            high: None,
        };
    }
    let mut low = vals[0];
    let mut high = vals[0];
    for v in vals {
        if *v < low {
            low = *v;
        }
        if *v > high {
            high = *v;
        }
    }
    let sum = vals.iter().fold(Decimal::ZERO, |acc, v| acc + v);
    St {
        n: vals.len(),
        low: Some(low),
        q1: Some(quantile(vals, Decimal::new(25, 2))),
        median: Some(quantile(vals, Decimal::new(5, 1))),
        mean: Some(py_div(sum, Decimal::from(vals.len() as i64))),
        q3: Some(quantile(vals, Decimal::new(75, 2))),
        high: Some(high),
    }
}

fn stats_json(st: &St) -> Value {
    let f = |d: Option<Decimal>| d.map_or(Value::Null, |v| json!(v.to_string()));
    json!({
        "n": st.n,
        "low": f(st.low),
        "q1": f(st.q1),
        "median": f(st.median),
        "mean": f(st.mean),
        "q3": f(st.q3),
        "high": f(st.high),
    })
}

/// Python implied_range(): (low, mid, high, note). The note says why there is no range.
fn implied_range(
    target: Decimal,
    st: &St,
) -> (Option<Decimal>, Option<Decimal>, Option<Decimal>, String) {
    if target <= Decimal::ZERO {
        return (None, None, None, "target metric not positive".into());
    }
    if st.n < MIN_PEERS {
        return (
            None,
            None,
            None,
            format!("only {} usable multiples, need {MIN_PEERS}", st.n),
        );
    }
    (
        st.q1.map(|q| target * q),
        st.median.map(|m| target * m),
        st.q3.map(|q| target * q),
        String::new(),
    )
}

fn is_stale_as_of(as_of: Option<&str>) -> bool {
    let Some(a) = as_of.filter(|a| !a.is_empty()) else {
        return false;
    };
    match NaiveDate::parse_from_str(a, "%Y-%m-%d") {
        Ok(d) => (Utc::now().date_naive() - d).num_days() > MAX_AS_OF_AGE_DAYS,
        Err(_) => true,
    }
}

async fn load_sources(
    tx: &mut Transaction<'_, Postgres>,
    id: i32,
) -> Result<Vec<SourceRec>, ApiError> {
    let rows: Vec<SourceRow> = sqlx::query_as(
        "SELECT document_id, page, quote, kind, section, heading, anchor FROM fact_source \
         WHERE fact_id = $1 ORDER BY id",
    )
    .bind(id)
    .fetch_all(&mut **tx)
    .await?;
    Ok(rows
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
        .collect())
}

/// Python `_find`: the latest visible verified fact for entity, metric and period.
async fn find(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    entity: &str,
    metric: &str,
    period: &str,
) -> Result<Option<CFact>, ApiError> {
    let rows: Vec<(i32, Decimal, String, String, Option<String>)> = sqlx::query_as(
        "SELECT id, value, unit, period, as_of FROM fact WHERE entity = $1 AND metric = $2 AND period = $3 \
         AND status = 'verified' ORDER BY id DESC",
    )
    .bind(entity)
    .bind(metric)
    .bind(period)
    .fetch_all(&mut **tx)
    .await?;
    for (id, value, unit, period, as_of) in rows {
        let sources = load_sources(tx, id).await?;
        let ids: Vec<&str> = sources.iter().map(|s| s.doc_id.as_str()).collect();
        if vis.fact_visible(&ids) {
            return Ok(Some(CFact {
                id,
                value: stored(value),
                unit,
                period,
                as_of,
                sources,
            }));
        }
    }
    Ok(None)
}

/// Python `_denominator`: a stored fact wins; otherwise a derived formula from its cited components.
async fn denominator(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    entity: &str,
    metric: &str,
    period: &str,
) -> Result<Option<Denom>, ApiError> {
    if let Some(f) = find(tx, vis, entity, metric, period).await? {
        return Ok(Some(Denom {
            value: f.value,
            unit: f.unit.clone(),
            fact: Some(f),
            formula: None,
        }));
    }
    if !derived::is_formula(metric) {
        return Ok(None);
    }
    // a component is missing, unverified, hidden or in another unit: no figure, never a guess
    match derived::derive(tx, vis, metric, entity, period).await {
        Ok(d) => Ok(Some(Denom {
            value: d.value,
            unit: d.unit.clone(),
            fact: None,
            formula: Some((
                metric.to_string(),
                d.components.iter().map(|c| c.fact_id).collect(),
            )),
        })),
        Err(_) => Ok(None),
    }
}

/// Python `_cite`: "doc <8 chars> <locator>" for each source, joined.
fn cite(f: &CFact) -> String {
    if f.sources.is_empty() {
        return "no source".into();
    }
    f.sources
        .iter()
        .map(|s| {
            let doc: String = s.doc_id.chars().take(8).collect();
            let loc = locator_label(
                s.page,
                s.section.as_deref(),
                s.heading.as_deref(),
                &s.kind,
                s.anchor.as_deref(),
            );
            format!("doc {doc} {loc}")
        })
        .collect::<Vec<_>>()
        .join("; ")
}

/// Python `_cell`: the period, as-of and cited source of one input.
fn cell(f: &CFact) -> Value {
    json!({
        "fact_id": f.id,
        "period": f.period,
        "as_of": f.as_of,
        "unit": f.unit,
        "source": cite(f),
    })
}

/// Python build_rows(): one row per peer. Each metric gets a multiple, or the reason it has none.
async fn build_rows(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    http: &reqwest::Client,
    entities: &[String],
    period: &str,
    metrics: &[String],
    ev_period: &str,
) -> Result<Vec<Peer>, ApiError> {
    let mut rows = Vec::new();
    for ent in entities {
        let ev = find(tx, vis, ent, EV_METRIC, ev_period).await?;
        let mut p = Peer {
            entity: ent.clone(),
            multiples: Vec::new(),
            nm: Map::new(),
            facts: Map::new(),
            fx: Map::new(),
            derived: Map::new(),
            cells: Map::new(),
            stale: Vec::new(),
        };
        if let Some(e) = &ev {
            p.facts.insert(EV_METRIC.into(), json!(e.id));
            p.cells.insert("ev".into(), cell(e));
        }
        for m in metrics {
            let (mult, reason) = 'metric: {
                let Some(e) = &ev else {
                    break 'metric (None, Some("no enterprise value fact".to_string()));
                };
                let Some(d) = denominator(tx, vis, ent, m, period).await? else {
                    break 'metric (None, Some(format!("no {m} fact for {period}")));
                };
                if let Some(f) = &d.fact {
                    p.facts.insert(m.clone(), json!(f.id));
                    p.cells.insert(m.clone(), cell(f));
                }
                if let Some((formula, comps)) = &d.formula {
                    p.derived
                        .insert(m.clone(), json!({"formula": formula, "components": comps}));
                    p.cells.insert(
                        m.clone(),
                        json!({"period": period, "unit": d.unit, "derived": formula, "components": comps}),
                    );
                }
                let mut denom = d.value;
                if e.unit != d.unit {
                    match fx::fx_rate(http, &d.unit, &e.unit).await {
                        Ok((rate, as_of, source)) => {
                            denom = d.value * rate;
                            p.fx.insert(
                                m.clone(),
                                json!({"from": d.unit, "to": e.unit, "rate": rate.to_string(),
                                       "as_of": as_of, "source": source}),
                            );
                        }
                        // no rate, or the rate source is unreachable: never a guess
                        Err(err) => {
                            break 'metric (
                                None,
                                Some(format!("no FX rate {} to {}: {err}", d.unit, e.unit)),
                            )
                        }
                    }
                }
                multiple(e.value, denom)
            };
            if mult.is_none() {
                p.nm.insert(m.clone(), json!(reason.unwrap_or_default()));
            }
            p.multiples.push((m.clone(), mult));
        }
        if let Some(e) = &ev {
            if e.period != period {
                p.stale.push("ev".into());
            }
            if is_stale_as_of(e.as_of.as_deref()) {
                p.stale.push("ev_as_of".into());
            }
        }
        rows.push(p);
    }
    Ok(rows)
}

/// Python run(): stats per metric, the target's implied range per metric, and every peer row.
async fn run(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    http: &reqwest::Client,
    body: &CompsIn,
) -> Result<Value, ApiError> {
    let ev_period = body
        .ev_period
        .as_deref()
        .filter(|s| !s.is_empty())
        .unwrap_or(&body.period);
    let target_period = body
        .target_period
        .as_deref()
        .filter(|s| !s.is_empty())
        .unwrap_or(&body.period);
    let entities: Vec<String> = body
        .peers
        .iter()
        .filter(|e| **e != body.target)
        .cloned()
        .collect();
    let rows = build_rows(
        tx,
        vis,
        http,
        &entities,
        &body.period,
        &body.metrics,
        ev_period,
    )
    .await?;

    let mut stats_out = Map::new();
    let mut implied = Vec::new();
    for m in &body.metrics {
        let vals: Vec<Decimal> = rows
            .iter()
            .filter_map(|r| {
                r.multiples
                    .iter()
                    .find(|(k, _)| k == m)
                    .and_then(|(_, v)| *v)
            })
            .collect();
        let st = stats(&vals);
        stats_out.insert(m.clone(), stats_json(&st));
        match denominator(tx, vis, &body.target, m, target_period).await? {
            None => implied.push(json!({
                "metric": m,
                "multiple": format!("EV/{m}"),
                "target_fact_id": null,
                "note": format!("no {m} fact for {}", body.target),
            })),
            Some(t) => {
                let (low, mid, high, note) = implied_range(t.value, &st);
                let f = |d: Option<Decimal>| d.map_or(Value::Null, |v| json!(v.to_string()));
                implied.push(json!({
                    "metric": m,
                    "multiple": format!("EV/{m}"),
                    "target_fact_id": t.fact.as_ref().map(|f| f.id),
                    "target_value": t.value.to_string(),
                    "unit": t.unit,
                    "note": note,
                    "derived": t.formula.as_ref().map(|(formula, comps)| json!({"formula": formula, "components": comps})),
                    "low": f(low),
                    "mid": f(mid),
                    "high": f(high),
                }));
            }
        }
    }

    let peers: Vec<Value> = rows
        .iter()
        .map(|r| {
            let multiples: Map<String, Value> = r
                .multiples
                .iter()
                .map(|(k, v)| {
                    let q = v.map_or(Value::Null, |d| json!(crate::comps::quantize_multiple(d)));
                    (k.clone(), q)
                })
                .collect();
            json!({
                "entity": r.entity,
                "facts": r.facts,
                "nm": r.nm,
                "fx": r.fx,
                "derived": r.derived,
                "cells": r.cells,
                "stale": r.stale,
                "multiples": multiples,
            })
        })
        .collect();

    Ok(json!({
        "target": body.target,
        "period": body.period,
        "peers": peers,
        "stats": stats_out,
        "implied": implied,
    }))
}

pub async fn calc_comps(
    State(s): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<CompsIn>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    if body.peers.len() > 200 || body.metrics.len() > 10 {
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "too many peers or metrics",
        ));
    }
    let vis = Visibility::load(&mut tx, &p).await?;
    let out = run(&mut tx, &vis, &s.http, &body).await?;
    tx.commit().await?;
    Ok(Json(out))
}
