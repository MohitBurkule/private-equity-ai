//! Port of GET /calc/periods (app/main.py calc_periods): the periods that have verified, visible facts for an entity,
//! oldest first, so a screen can default to periods that exist.

use crate::auth::principal;
use crate::citations::locator_label;
use crate::error::ApiError;
use crate::facts::stored;
use crate::visibility::Visibility;
use crate::AppState;
use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    Json,
};
use rust_decimal::{Decimal, RoundingStrategy};
use serde_json::{json, Value};
use sqlx::{Postgres, Transaction};
use std::collections::HashMap;
use std::collections::{BTreeMap, BTreeSet};

pub async fn calc_periods(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let entity = q
        .get("entity")
        .ok_or_else(|| ApiError::missing_query("entity"))?;
    let vis = Visibility::load(&mut tx, &p).await?;
    let facts: Vec<(i32, String)> =
        sqlx::query_as("SELECT id, period FROM fact WHERE entity = $1 AND status = 'verified'")
            .bind(entity)
            .fetch_all(&mut *tx)
            .await?;
    let sources: Vec<(i32, String)> =
        sqlx::query_as("SELECT fact_id, document_id FROM fact_source ORDER BY id")
            .fetch_all(&mut *tx)
            .await?;
    tx.commit().await?;
    let mut docs: BTreeMap<i32, Vec<&str>> = BTreeMap::new();
    for (fact_id, doc_id) in &sources {
        docs.entry(*fact_id).or_default().push(doc_id.as_str());
    }
    let mut periods: BTreeSet<&str> = BTreeSet::new();
    for (id, period) in &facts {
        let ids = docs.get(id).map(Vec::as_slice).unwrap_or(&[]);
        if vis.fact_visible(ids) {
            periods.insert(period.as_str());
        }
    }
    Ok(Json(
        json!({ "entity": entity, "periods": periods.into_iter().collect::<Vec<_>>() }),
    ))
}

/// fact_source columns find() reads: document, page, quote, kind, section, heading, anchor.
type SourceRow = (
    String,
    i32,
    String,
    String,
    Option<String>,
    Option<String>,
    Option<String>,
);

/// A verified fact that passed visibility, with the citations calc output reports.
struct Found {
    id: i32,
    metric: String,
    period: String,
    value: Decimal,
    unit: String,
    basis: String,
    sources: Vec<Value>,
}

/// One term of a formula: role, sign, and the fact it resolved to.
struct Input {
    role: &'static str,
    sign: i32,
    fact: Found,
}

/// Port of app/calc.py Calc. The value stands only when every input is found, shares one unit and one basis.
struct Calc {
    name: String,
    entity: String,
    formula: String,
    value: Option<Decimal>,
    unit: Option<String>,
    inputs: Vec<Input>,
    missing: Vec<String>,
    problems: Vec<String>,
}

/// Python list repr of sorted strings, e.g. ['EUR', 'USD'], for the problem messages.
fn py_list(items: &BTreeSet<String>) -> String {
    let parts: Vec<String> = items.iter().map(|s| format!("'{s}'")).collect();
    format!("[{}]", parts.join(", "))
}

/// _find: the latest verified fact for the metric and period that the caller may see.
async fn find(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    entity: &str,
    metric: &str,
    period: &str,
) -> Result<Option<Found>, ApiError> {
    let rows: Vec<(i32, String, String, Decimal, String, String)> = sqlx::query_as(
        "SELECT id, metric, period, value, unit, basis FROM fact \
         WHERE entity = $1 AND metric = $2 AND period = $3 AND status = 'verified' ORDER BY id DESC",
    )
    .bind(entity)
    .bind(metric)
    .bind(period)
    .fetch_all(&mut **tx)
    .await?;
    for (id, metric, period, value, unit, basis) in rows {
        let srcs: Vec<SourceRow> = sqlx::query_as(
            "SELECT document_id, page, quote, kind, section, heading, anchor FROM fact_source \
                 WHERE fact_id = $1 ORDER BY id",
        )
        .bind(id)
        .fetch_all(&mut **tx)
        .await?;
        let doc_ids: Vec<&str> = srcs.iter().map(|s| s.0.as_str()).collect();
        if !vis.fact_visible(&doc_ids) {
            continue;
        }
        let sources = srcs
            .iter()
            .map(|s| {
                json!({
                    "document_id": s.0,
                    "page": s.1,
                    "locator": locator_label(s.1, s.4.as_deref(), s.5.as_deref(), &s.3, s.6.as_deref()),
                    "quote": s.2,
                })
            })
            .collect();
        return Ok(Some(Found {
            id,
            metric,
            period,
            value: stored(value),
            unit,
            basis,
            sources,
        }));
    }
    Ok(None)
}

/// _combine: resolve every (role, metric, period, sign) term, then the value when the set is complete.
async fn combine(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    c: &mut Calc,
    wanted: &[(&'static str, &str, &str, i32)],
) -> Result<(), ApiError> {
    for (role, metric, period, sign) in wanted {
        match find(tx, vis, &c.entity, metric, period).await? {
            None => c.missing.push(format!("{role}: {metric} for {period}")),
            Some(fact) => c.inputs.push(Input {
                role,
                sign: *sign,
                fact,
            }),
        }
    }
    if c.missing.is_empty() {
        finish(c);
    }
    Ok(())
}

/// The unit, basis and sum checks shared by every calc once all inputs are in hand.
fn finish(c: &mut Calc) {
    let units: BTreeSet<String> = c.inputs.iter().map(|i| i.fact.unit.clone()).collect();
    if units.len() != 1 {
        c.problems
            .push(format!("inputs use different units: {}", py_list(&units)));
        return;
    }
    c.unit = units.into_iter().next();
    let bases: BTreeSet<String> = c.inputs.iter().map(|i| i.fact.basis.clone()).collect();
    if bases.len() != 1 {
        // Reported and adjusted figures never add together.
        c.problems
            .push(format!("inputs mix bases: {}", py_list(&bases)));
        return;
    }
    c.value = Some(c.inputs.iter().fold(Decimal::ZERO, |acc, i| {
        acc + if i.sign < 0 {
            -i.fact.value
        } else {
            i.fact.value
        }
    }));
}

/// Python DEBT_LIKE: optional items that sit outside net debt but reduce the equity price.
const DEBT_LIKE: [(&str, &str); 4] = [
    ("pension", "pension_deficit"),
    ("deferred", "deferred_consideration"),
    ("earnout", "earn_out"),
    ("tax", "unpaid_tax"),
];

/// Python net_debt(): total_debt (+ lease_liabilities) - cash.
async fn net_debt(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    entity: &str,
    period: &str,
    include_leases: bool,
) -> Result<Calc, ApiError> {
    let formula = format!(
        "debt{} - cash",
        if include_leases { " + leases" } else { "" }
    );
    let mut c = Calc::new("Net debt".into(), entity, formula);
    let mut wanted = vec![("debt", "total_debt", period, 1)];
    if include_leases {
        wanted.push(("leases", "lease_liabilities", period, 1));
    }
    wanted.push(("cash", "cash", period, -1));
    combine(tx, vis, &mut c, &wanted).await?;
    Ok(c)
}

/// Python debt_like(): the stated debt-like items; the metrics not found are listed, never counted as zero.
async fn debt_like(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    entity: &str,
    period: &str,
) -> Result<(Calc, Vec<String>), ApiError> {
    let names: Vec<&str> = DEBT_LIKE.iter().map(|(_, m)| *m).collect();
    let mut c = Calc::new(
        "Debt-like items".into(),
        entity,
        format!("sum of {} stated", names.join(", ")),
    );
    let mut not_found = Vec::new();
    for (role, metric) in DEBT_LIKE {
        match find(tx, vis, entity, metric, period).await? {
            None => not_found.push(metric.to_string()),
            Some(fact) => c.inputs.push(Input {
                role,
                sign: 1,
                fact,
            }),
        }
    }
    if c.inputs.is_empty() {
        c.missing
            .push("no debt-like item stated for this period".into());
    } else {
        finish(&mut c);
    }
    Ok((c, not_found))
}

/// FastAPI's bool query parsing for include_leases (default true).
fn include_leases(q: &HashMap<String, String>) -> Result<bool, ApiError> {
    let Some(raw) = q.get("include_leases") else {
        return Ok(true);
    };
    match raw.to_ascii_lowercase().as_str() {
        "true" | "1" | "yes" | "on" => Ok(true),
        "false" | "0" | "no" | "off" => Ok(false),
        _ => Err(ApiError(
            StatusCode::UNPROCESSABLE_ENTITY,
            "validation error".into(),
            Some(json!([{
                "type": "bool_parsing", "loc": ["query", "include_leases"],
                "msg": "Input should be a valid boolean, unable to interpret input", "input": raw,
            }])),
        )),
    }
}

/// Shared parameter check for the period routes: entity and period are required.
fn entity_period_query(q: &HashMap<String, String>) -> Result<(String, String), ApiError> {
    let missing: Vec<Value> = ["entity", "period"]
        .iter()
        .filter(|name| !q.contains_key(**name))
        .map(|name| json!({ "type": "missing", "loc": ["query", name], "msg": "Field required", "input": null }))
        .collect();
    if !missing.is_empty() {
        return Err(ApiError(
            StatusCode::UNPROCESSABLE_ENTITY,
            "validation error".into(),
            Some(Value::Array(missing)),
        ));
    }
    Ok((q["entity"].clone(), q["period"].clone()))
}

/// Python nwc(): (current assets - cash) - (current liabilities - short-term debt).
async fn nwc(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    entity: &str,
    period: &str,
) -> Result<Calc, ApiError> {
    let mut c = Calc::new(
        "Net working capital".into(),
        entity,
        "(current assets - cash) - (current liabilities - short-term debt)".into(),
    );
    combine(
        tx,
        vis,
        &mut c,
        &[
            ("current assets", "current_assets", period, 1),
            ("cash", "cash", period, -1),
            ("current liabilities", "current_liabilities", period, -1),
            ("short-term debt", "short_term_debt", period, 1),
        ],
    )
    .await?;
    Ok(c)
}

pub async fn calc_nwc(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let (entity, period) = entity_period_query(&q)?;
    let vis = Visibility::load(&mut tx, &p).await?;
    let c = nwc(&mut tx, &vis, &entity, &period).await?;
    tx.commit().await?;
    Ok(Json(c.to_json()))
}

/// Python nwc_peg(): the average trade NWC over the given periods. Every period must be complete, so a peg built from a
/// partial set never moves silently when a missing period is later loaded.
async fn nwc_peg(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    entity: &str,
    periods: &[String],
) -> Result<Calc, ApiError> {
    let mut c = Calc::new(
        "NWC peg".into(),
        entity,
        format!("average of trade NWC over {}", periods.join(", ")),
    );
    c.unit = Some("USD".into());
    if periods.is_empty() {
        c.missing.push("no periods given for the peg".into());
        return Ok(c);
    }
    let mut values = Vec::new();
    for p in periods {
        let n = nwc(tx, vis, entity, p).await?;
        match (n.value, n.unit.as_deref()) {
            (None, _) => {
                let items = if n.missing.is_empty() {
                    &n.problems
                } else {
                    &n.missing
                };
                c.missing.extend(items.iter().map(|m| format!("{p} {m}")));
            }
            (Some(_), unit) if unit != Some("USD") => {
                c.problems.push(format!(
                    "{p} NWC is in {}, expected USD",
                    unit.unwrap_or_default()
                ));
            }
            (Some(v), _) => values.push(v),
        }
    }
    if c.missing.is_empty() && c.problems.is_empty() {
        let total = values.iter().fold(Decimal::ZERO, |acc, v| acc + v);
        let mut avg = (total / Decimal::from(values.len()))
            .round_dp_with_strategy(2, RoundingStrategy::MidpointNearestEven);
        avg.rescale(2);
        c.value = Some(avg);
    }
    Ok(c)
}

/// Splits the comma-separated periods parameter the way FastAPI does: strip, drop empties.
fn split_periods(raw: &str) -> Vec<String> {
    raw.split(',')
        .map(str::trim)
        .filter(|p| !p.is_empty())
        .map(String::from)
        .collect()
}

pub async fn calc_nwc_peg(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let missing: Vec<Value> = ["entity", "periods"]
        .iter()
        .filter(|name| !q.contains_key(**name))
        .map(|name| json!({ "type": "missing", "loc": ["query", name], "msg": "Field required", "input": null }))
        .collect();
    if !missing.is_empty() {
        return Err(ApiError(
            StatusCode::UNPROCESSABLE_ENTITY,
            "validation error".into(),
            Some(Value::Array(missing)),
        ));
    }
    let entity = q["entity"].clone();
    let periods = split_periods(&q["periods"]);
    let vis = Visibility::load(&mut tx, &p).await?;
    let peg = nwc_peg(&mut tx, &vis, &entity, &periods).await?;
    let mut per_period = serde_json::Map::new();
    for period in &periods {
        let c = nwc(&mut tx, &vis, &entity, period).await?;
        per_period.insert(period.clone(), c.to_json());
    }
    tx.commit().await?;
    let mut out = peg.to_json();
    out["per_period"] = Value::Object(per_period);
    Ok(Json(out))
}

pub async fn calc_net_debt(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let (entity, period) = entity_period_query(&q)?;
    let leases = include_leases(&q)?;
    let vis = Visibility::load(&mut tx, &p).await?;
    let c = net_debt(&mut tx, &vis, &entity, &period, leases).await?;
    tx.commit().await?;
    Ok(Json(c.to_json()))
}

/// Python net_debt_adjusted(): the adjusted figure exists only when net debt and a debt-like item are both stated.
pub async fn calc_net_debt_adjusted(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let (entity, period) = entity_period_query(&q)?;
    let leases = include_leases(&q)?;
    let vis = Visibility::load(&mut tx, &p).await?;
    let nd = net_debt(&mut tx, &vis, &entity, &period, leases).await?;
    let (dl, not_found) = debt_like(&mut tx, &vis, &entity, &period).await?;
    tx.commit().await?;
    let adjusted = match (nd.value, dl.value) {
        (Some(n), Some(d)) if nd.unit == dl.unit => Some((n + d).to_string()),
        _ => None,
    };
    Ok(Json(json!({
        "net_debt": nd.to_json(), "debt_like": dl.to_json(), "not_found": not_found, "adjusted": adjusted,
    })))
}

impl Calc {
    fn new(name: String, entity: &str, formula: String) -> Self {
        Calc {
            name,
            entity: entity.into(),
            formula,
            value: None,
            unit: None,
            inputs: Vec::new(),
            missing: Vec::new(),
            problems: Vec::new(),
        }
    }

    /// Python _calc_out.
    fn to_json(&self) -> Value {
        let inputs: Vec<Value> = self
            .inputs
            .iter()
            .map(|i| {
                json!({
                    "role": i.role, "sign": i.sign, "fact_id": i.fact.id, "metric": i.fact.metric,
                    "period": i.fact.period, "value": i.fact.value.to_string(), "unit": i.fact.unit,
                    "sources": i.fact.sources,
                })
            })
            .collect();
        json!({
            "name": self.name, "entity": self.entity, "ok": self.value.is_some(),
            "value": self.value.map(|v| v.to_string()), "unit": self.unit, "formula": self.formula,
            "missing": self.missing, "problems": self.problems, "inputs": inputs,
        })
    }
}

/// Python ltm(): last fiscal year + current YTD - prior-year YTD, same metric.
pub async fn calc_ltm(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let missing: Vec<Value> = ["entity", "metric", "fy", "ytd", "ytd_prior"]
        .iter()
        .filter(|name| !q.contains_key(**name))
        .map(|name| json!({ "type": "missing", "loc": ["query", name], "msg": "Field required", "input": null }))
        .collect();
    if !missing.is_empty() {
        return Err(ApiError(
            StatusCode::UNPROCESSABLE_ENTITY,
            "validation error".into(),
            Some(Value::Array(missing)),
        ));
    }
    let (entity, metric) = (q["entity"].as_str(), q["metric"].as_str());
    let (fy, ytd, ytd_prior) = (q["fy"].as_str(), q["ytd"].as_str(), q["ytd_prior"].as_str());
    let vis = Visibility::load(&mut tx, &p).await?;
    let mut c = Calc::new(
        format!("LTM {metric}"),
        entity,
        format!("{fy} + {ytd} - {ytd_prior}"),
    );
    combine(
        &mut tx,
        &vis,
        &mut c,
        &[
            ("fiscal year", metric, fy, 1),
            ("current YTD", metric, ytd, 1),
            ("prior YTD", metric, ytd_prior, -1),
        ],
    )
    .await?;
    tx.commit().await?;
    Ok(Json(c.to_json()))
}

/// fact_source rows for one fact, in insertion order.
async fn sources_of(
    tx: &mut Transaction<'_, Postgres>,
    id: i32,
) -> Result<Vec<SourceRow>, ApiError> {
    Ok(sqlx::query_as(
        "SELECT document_id, page, quote, kind, section, heading, anchor FROM fact_source \
         WHERE fact_id = $1 ORDER BY id",
    )
    .bind(id)
    .fetch_all(&mut **tx)
    .await?)
}

/// Citation JSON for a fact's sources, as calc output reports them.
fn citations(srcs: &[SourceRow]) -> Vec<Value> {
    srcs.iter()
        .map(|s| {
            json!({
                "document_id": s.0,
                "page": s.1,
                "locator": locator_label(s.1, s.4.as_deref(), s.5.as_deref(), &s.3, s.6.as_deref()),
                "quote": s.2,
            })
        })
        .collect()
}

/// Python normalized_ebitda's line query: visible USD "ebitda_bridge ..." facts for the period, in id order, with status.
async fn bridge_lines(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    entity: &str,
    period: &str,
) -> Result<Vec<(Found, String)>, ApiError> {
    let rows: Vec<(i32, String, Decimal, String, String, String)> = sqlx::query_as(
        "SELECT id, metric, value, unit, basis, status FROM fact \
         WHERE entity = $1 AND period = $2 AND unit = 'USD' AND metric LIKE 'ebitda_bridge %' ORDER BY id",
    )
    .bind(entity)
    .bind(period)
    .fetch_all(&mut **tx)
    .await?;
    let mut out = Vec::new();
    for (id, metric, value, unit, basis, status) in rows {
        let srcs = sources_of(tx, id).await?;
        let doc_ids: Vec<&str> = srcs.iter().map(|s| s.0.as_str()).collect();
        if !vis.fact_visible(&doc_ids) {
            continue;
        }
        let fact = Found {
            id,
            metric,
            period: period.into(),
            value: stored(value),
            unit,
            basis,
            sources: citations(&srcs),
        };
        out.push((fact, status));
    }
    Ok(out)
}

/// Python normalized_ebitda(): reported EBITDA + reviewed add-backs - deductions. Withheld while any line is unreviewed.
async fn normalized_ebitda(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    entity: &str,
    period: &str,
) -> Result<Calc, ApiError> {
    let mut c = Calc::new(
        "Normalized EBITDA".into(),
        entity,
        "reported + add-backs - deductions".into(),
    );
    c.unit = Some("USD".into());
    let lines = bridge_lines(tx, vis, entity, period).await?;
    let unreviewed: Vec<i32> = lines
        .iter()
        .filter(|(_, status)| status != "verified" && status != "rejected")
        .map(|(f, _)| f.id)
        .collect();
    if !unreviewed.is_empty() {
        c.missing.push(format!(
            "{} bridge line(s) not yet reviewed: ids {:?}",
            unreviewed.len(),
            unreviewed
        ));
        return Ok(c);
    }
    let reported = lines
        .iter()
        .filter(|(f, status)| status == "verified" && f.metric == "ebitda_bridge reported")
        .count();
    if reported != 1 {
        c.missing.push(format!(
            "reported EBITDA: expected one reviewed line, found {reported}"
        ));
        return Ok(c);
    }
    for (fact, status) in lines {
        if status != "verified" {
            continue;
        }
        let (role, sign) = match fact
            .metric
            .strip_prefix("ebitda_bridge ")
            .unwrap_or_default()
        {
            "reported" => ("reported", 1),
            "add_back" => ("add_back", 1),
            "deduction" => ("deduction", -1),
            _ => continue, // adjusted totals are not summed: the bridge check compares them, nothing else reads them
        };
        c.inputs.push(Input { role, sign, fact });
    }
    c.value = Some(c.inputs.iter().fold(Decimal::ZERO, |acc, i| {
        acc + if i.sign < 0 {
            -i.fact.value
        } else {
            i.fact.value
        }
    }));
    Ok(c)
}

/// Python _row_label: the row name a bridge quote carries after "row:", or the whole quote.
fn row_label(quote: &str) -> &str {
    quote.split_once("row:").map_or(quote, |(_, row)| row)
}

/// Python one_off_flags(): add-backs above 10% of reported EBITDA, excluding standard EBITDA components.
fn one_off_flags(c: &Calc) -> Vec<Value> {
    if c.value.is_none() {
        return Vec::new();
    }
    let Some(reported) = c
        .inputs
        .iter()
        .find(|i| i.role == "reported")
        .map(|i| i.fact.value)
    else {
        return Vec::new();
    };
    if reported.is_zero() {
        return Vec::new();
    }
    let limit = reported.abs() * Decimal::from(10) / Decimal::from(100);
    let standard =
        fancy_regex::Regex::new(r"(?i)interest|\btax|depreciation|amorti[sz]ation|\bd&a\b")
            .expect("static pattern");
    c.inputs
        .iter()
        .filter(|i| i.role == "add_back" && i.fact.value > limit)
        .filter(|i| {
            let quote = i
                .fact
                .sources
                .first()
                .and_then(|s| s["quote"].as_str())
                .unwrap_or_default();
            !standard.is_match(row_label(quote)).unwrap_or(false)
        })
        .map(|i| {
            let first = i.fact.sources.first();
            json!({
                "fact_id": i.fact.id,
                "amount": i.fact.value.to_string(),
                "quote": first.map_or(Value::Null, |s| s["quote"].clone()),
                "locator": first.map_or(Value::Null, |s| s["locator"].clone()),
            })
        })
        .collect()
}

pub async fn calc_normalized_ebitda(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let (entity, period) = entity_period_query(&q)?;
    let vis = Visibility::load(&mut tx, &p).await?;
    let c = normalized_ebitda(&mut tx, &vis, &entity, &period).await?;
    tx.commit().await?;
    let mut out = c.to_json();
    out["one_off_flags"] = Value::Array(one_off_flags(&c));
    Ok(Json(out))
}

/// Rounds a percentage to one decimal place, half to even, as Python's quantize(Decimal("0.1")).
fn one_dp(d: Decimal) -> String {
    let mut r = d.round_dp_with_strategy(1, RoundingStrategy::MidpointNearestEven);
    r.rescale(1);
    r.to_string()
}

/// Python revenue_trend(): revenue, growth on the prior listed period, and normalized EBITDA margin, per period.
pub async fn calc_revenue_trend(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let missing: Vec<Value> = ["entity", "periods"]
        .iter()
        .filter(|name| !q.contains_key(**name))
        .map(|name| json!({ "type": "missing", "loc": ["query", name], "msg": "Field required", "input": null }))
        .collect();
    if !missing.is_empty() {
        return Err(ApiError(
            StatusCode::UNPROCESSABLE_ENTITY,
            "validation error".into(),
            Some(Value::Array(missing)),
        ));
    }
    let entity = q["entity"].clone();
    let vis = Visibility::load(&mut tx, &p).await?;
    let mut rows = Vec::new();
    let mut prev: Option<Decimal> = None;
    for period in split_periods(&q["periods"]) {
        let mut row = json!({ "period": period, "revenue": null, "growth_pct": null, "ebitda_margin_pct": null });
        let mut gaps: Vec<String> = Vec::new();
        match find(&mut tx, &vis, &entity, "revenue", &period).await? {
            None => gaps.push(format!("revenue for {period}")),
            Some(rev) => {
                row["revenue"] = json!(rev.value.to_string());
                if let Some(pv) = prev.filter(|pv| !pv.is_zero()) {
                    row["growth_pct"] =
                        json!(one_dp((rev.value / pv - Decimal::ONE) * Decimal::from(100)));
                }
                prev = Some(rev.value);
                let ebitda = normalized_ebitda(&mut tx, &vis, &entity, &period).await?;
                match ebitda.value {
                    Some(e) if !rev.value.is_zero() => {
                        row["ebitda_margin_pct"] =
                            json!(one_dp(e / rev.value * Decimal::from(100)));
                    }
                    _ if ebitda.missing.is_empty() => gaps.push("normalized EBITDA".into()),
                    _ => gaps.extend(ebitda.missing),
                }
            }
        }
        row["missing"] = json!(gaps);
        rows.push(row);
    }
    tx.commit().await?;
    Ok(Json(json!({ "entity": entity, "rows": rows })))
}
