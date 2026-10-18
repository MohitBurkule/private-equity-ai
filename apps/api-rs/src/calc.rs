//! Port of GET /calc/periods (app/main.py calc_periods): the periods that have verified, visible facts for an entity,
//! oldest first, so a screen can default to periods that exist.

use crate::auth::principal;
use crate::citations::locator_label;
use crate::error::ApiError;
use crate::visibility::Visibility;
use crate::AppState;
use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode},
    Json,
};
use rust_decimal::Decimal;
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
        // Numeric(24, 6) values read back with scale 6 in Python; sqlx returns a zero unscaled.
        let mut value = value;
        value.rescale(6);
        return Ok(Some(Found {
            id,
            metric,
            period,
            value,
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
