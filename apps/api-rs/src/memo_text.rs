//! Port of GET /memo and GET /memo/sections (app/main.py, app/memo.py, app/memo_templates.py) for the text the
//! builder makes from cited facts and firm rules. A request that asks for trading comps (peers with a period) or a
//! legal review (legal_doc) needs modules the Rust API does not have yet, so it is relayed to FastAPI unchanged.

use crate::auth::principal;
use crate::citations::locator_label;
use crate::comps;
use crate::error::ApiError;
use crate::memo::BUILT_IN;
use crate::proxy;
use crate::visibility::Visibility;
use crate::AppState;
use axum::{
    extract::{Query, Request, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use rust_decimal::{Decimal, RoundingStrategy};
use serde_json::{json, Value};
use sqlx::{Postgres, Transaction};
use std::collections::{BTreeMap, BTreeSet, HashMap};

/// Python memo.MARGINS: (label, numerator metric, denominator metric).
const MARGINS: [(&str, &str, &str); 3] = [
    ("gross margin", "gross_profit", "revenue"),
    ("operating margin", "operating_income", "revenue"),
    ("net margin", "net_income", "revenue"),
];

/// Python firm_knowledge.APPLIED_KEYS with their labels (TERMS).
const APPLIED: [(&str, &str); 3] = [
    ("lp_reporting_tone", "LP reporting tone"),
    ("partner_signoff_threshold", "Partner sign-off threshold"),
    ("board_meeting_frequency", "Board meeting frequency"),
];

/// Python memo_templates.SECTIONS: section key -> default heading.
const SECTIONS: [(&str, &str); 4] = [
    ("financial", "Financial summary"),
    ("derived", "Derived (computed in code)"),
    ("risks", "Risks shown by the cited figures"),
    ("rules", "Firm rules applied (accepted, quoted)"),
];

/// Python _fmt: quantize to cents, half up, with thousands separators.
fn fmt(v: Decimal) -> String {
    let mut q = v.round_dp_with_strategy(2, RoundingStrategy::MidpointAwayFromZero);
    q.rescale(2);
    let text = q.abs().to_string();
    let (whole, cents) = text.split_once('.').unwrap_or((&text, "00"));
    let mut grouped = String::new();
    for (i, c) in whole.chars().enumerate() {
        if i > 0 && (whole.len() - i) % 3 == 0 {
            grouped.push(',');
        }
        grouped.push(c);
    }
    let sign = if q.is_sign_negative() { "-" } else { "" };
    format!("{sign}{grouped}.{cents}")
}

/// Python _gloss: the exact figure, plus a short reading aid for large values.
fn gloss(v: Decimal) -> String {
    let a = v.abs();
    let sizes = [
        (Decimal::from(1_000_000_000_000i64), "T"),
        (Decimal::from(1_000_000_000i64), "B"),
        (Decimal::from(1_000_000i64), "M"),
    ];
    for (size, tag) in sizes {
        if a >= size {
            let mut reading =
                (v / size).round_dp_with_strategy(2, RoundingStrategy::MidpointAwayFromZero);
            reading.rescale(2);
            return format!("{} (about {reading}{tag})", fmt(v));
        }
    }
    fmt(v)
}

/// fact_source row: fact_id, document_id, page, quote, kind, section, heading, anchor.
type SourceRow = (
    i32,
    String,
    i32,
    String,
    String,
    Option<String>,
    Option<String>,
    Option<String>,
);

/// Python memo.Cited: a plain fact's value, unit and note number.
#[derive(Clone)]
struct Cited {
    value: Decimal,
    unit: String,
    note: i32,
}

/// Python dict semantics: a repeated key keeps its first position and takes the later value.
fn put(plain: &mut Vec<((String, String), Cited)>, key: (String, String), val: Cited) {
    match plain.iter().position(|(k, _)| *k == key) {
        Some(pos) => plain[pos].1 = val,
        None => plain.push((key, val)),
    }
}

fn get<'a>(
    plain: &'a [((String, String), Cited)],
    metric: &str,
    period: &str,
) -> Option<&'a Cited> {
    plain
        .iter()
        .find(|((m, p), _)| m == metric && p == period)
        .map(|(_, c)| c)
}

fn periods_of(plain: &[((String, String), Cited)]) -> Vec<String> {
    let set: BTreeSet<&str> = plain.iter().map(|((_, p), _)| p.as_str()).collect();
    set.into_iter().map(str::to_string).collect()
}

#[derive(Clone)]
struct Rule {
    label: &'static str,
    value: String,
    document_id: String,
    page: i32,
    quote: String,
}

#[derive(Default)]
struct Memo {
    lines: Vec<String>,
    derived: Vec<String>,
    notes: Vec<String>,
    rules: Vec<Rule>,
    risks: Vec<String>,
    comps: Vec<String>,
}

/// Python memo.build_memo_data, for a caller whose visible facts are `vis`.
async fn build_data(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    entity: &str,
) -> Result<Memo, ApiError> {
    let facts: Vec<(i32, String, String, Decimal, String, String)> = sqlx::query_as(
        "SELECT id, metric, period, value, unit, basis FROM fact \
         WHERE entity = $1 AND status = 'verified' ORDER BY period, metric, id",
    )
    .bind(entity)
    .fetch_all(&mut **tx)
    .await?;
    let ids: Vec<i32> = facts.iter().map(|f| f.0).collect();
    let sources: Vec<SourceRow> = sqlx::query_as(
        "SELECT fact_id, document_id, page, quote, kind, section, heading, anchor FROM fact_source \
         WHERE fact_id = ANY($1) ORDER BY id",
    )
    .bind(&ids)
    .fetch_all(&mut **tx)
    .await?;
    let doc_ids: Vec<String> = sources.iter().map(|s| s.1.clone()).collect();
    let docs: HashMap<String, String> = sqlx::query_as::<_, (String, String)>(
        "SELECT id, filename FROM document WHERE id = ANY($1)",
    )
    .bind(&doc_ids)
    .fetch_all(&mut **tx)
    .await?
    .into_iter()
    .collect();

    let mut memo = Memo::default();
    let mut plain: Vec<((String, String), Cited)> = Vec::new();
    for (id, metric, period, value, unit, basis) in &facts {
        let mine: Vec<&SourceRow> = sources.iter().filter(|s| s.0 == *id).collect();
        let ids: Vec<&str> = mine.iter().map(|s| s.1.as_str()).collect();
        // Python fact_visible plus `f.sources[0]`: a fact with no source is never shown.
        let Some(src) = mine.first() else { continue };
        if !vis.fact_visible(&ids) {
            continue;
        }
        let n = memo.notes.len() as i32 + 1;
        let filename = docs
            .get(&src.1)
            .cloned()
            .unwrap_or_else(|| src.1[..8].to_string());
        let where_ = locator_label(
            src.2,
            src.5.as_deref(),
            src.6.as_deref(),
            &src.4,
            src.7.as_deref(),
        );
        memo.notes
            .push(format!("[{n}] {filename}, {where_}: \"{}\"", src.3.trim()));
        memo.lines.push(format!(
            "{metric} ({period}, {basis}): {} {unit} [{n}]",
            gloss(*value)
        ));
        put(
            &mut plain,
            (metric.clone(), period.clone()),
            Cited {
                value: *value,
                unit: unit.clone(),
                note: n,
            },
        );
    }

    // Net debt = long-term debt less cash, only when both are in one unit (derived.net_debt_points).
    let mut net_debt: BTreeMap<String, (Decimal, String, (i32, i32))> = BTreeMap::new();
    for ((metric, period), debt) in &plain {
        if metric != "long_term_debt" {
            continue;
        }
        if let Some(cash) = get(&plain, "cash", period).filter(|c| c.unit == debt.unit) {
            net_debt.insert(
                period.clone(),
                (
                    debt.value - cash.value,
                    debt.unit.clone(),
                    (debt.note, cash.note),
                ),
            );
        }
    }
    for (p, (v, u, (a, b))) in &net_debt {
        memo.derived.push(format!(
            "net debt ({p}): {} {u} = long_term_debt - cash [{a}, {b}]",
            gloss(*v)
        ));
    }
    memo.derived.extend(derive_lines(&plain));
    memo.risks = risk_lines(&plain);

    for key in APPLIED {
        let row: Option<(String, String, i32, String)> = sqlx::query_as(
            "SELECT value, document_id, page, quote FROM firm_knowledge \
             WHERE key = $1 AND status = 'accepted' ORDER BY id DESC LIMIT 1",
        )
        .bind(key.0)
        .fetch_optional(&mut **tx)
        .await?;
        // A rule whose source the caller may not see is left out (applied_rules).
        if let Some((value, document_id, page, quote)) = row {
            if vis.fact_visible(&[document_id.as_str()]) {
                memo.rules.push(Rule {
                    label: key.1,
                    value,
                    document_id,
                    page,
                    quote,
                });
            }
        }
    }
    Ok(memo)
}

/// Python memo.derive_lines: margins, free cash flow and year-on-year revenue growth, each with its note numbers.
fn derive_lines(plain: &[((String, String), Cited)]) -> Vec<String> {
    let mut out = Vec::new();
    let periods = periods_of(plain);
    for (label, num, den) in MARGINS {
        for period in &periods {
            if let (Some(n), Some(d)) = (get(plain, num, period), get(plain, den, period)) {
                if d.value != Decimal::ZERO && n.unit == d.unit {
                    out.push(format!(
                        "{label} ({period}): {}% = {num} [{}] / {den} [{}]",
                        fmt(n.value / d.value * Decimal::from(100)),
                        n.note,
                        d.note
                    ));
                }
            }
        }
    }
    for period in &periods {
        if let (Some(o), Some(c)) = (
            get(plain, "operating_cash_flow", period),
            get(plain, "capex", period),
        ) {
            if o.unit == c.unit {
                out.push(format!(
                    "free cash flow ({period}): {} {} = operating_cash_flow [{}] - capex [{}]",
                    fmt(o.value - c.value.abs()),
                    o.unit,
                    o.note,
                    c.note
                ));
            }
        }
    }
    for pair in periods.windows(2) {
        let (prev, cur) = (&pair[0], &pair[1]);
        if let (Some(p), Some(c)) = (get(plain, "revenue", prev), get(plain, "revenue", cur)) {
            if p.value != Decimal::ZERO && p.unit == c.unit {
                out.push(format!(
                    "revenue growth ({cur} vs {prev}): {}% = revenue [{}] vs revenue [{}]",
                    fmt((c.value - p.value) / p.value * Decimal::from(100)),
                    c.note,
                    p.note
                ));
            }
        }
    }
    out
}

/// Python memo.risk_lines: losses, falling revenue and negative free cash flow the cited figures show.
fn risk_lines(plain: &[((String, String), Cited)]) -> Vec<String> {
    let mut out = Vec::new();
    // Python sorts by period, stably, so equal periods keep their insertion order.
    let mut sorted: Vec<&((String, String), Cited)> = plain.iter().collect();
    sorted.sort_by(|a, b| a.0 .1.cmp(&b.0 .1));
    for ((metric, period), c) in sorted {
        if (metric == "net_income" || metric == "operating_income") && c.value < Decimal::ZERO {
            out.push(format!(
                "{} negative in {period} ({}) [{}]",
                metric.replace('_', " "),
                fmt(c.value),
                c.note
            ));
        }
    }
    let periods = periods_of(plain);
    for pair in periods.windows(2) {
        let (prev, cur) = (&pair[0], &pair[1]);
        if let (Some(p), Some(c)) = (get(plain, "revenue", prev), get(plain, "revenue", cur)) {
            if p.unit == c.unit && c.value < p.value {
                out.push(format!(
                    "revenue fell in {cur} vs {prev} [{}, {}]",
                    c.note, p.note
                ));
            }
        }
    }
    for period in &periods {
        if let (Some(o), Some(c)) = (
            get(plain, "operating_cash_flow", period),
            get(plain, "capex", period),
        ) {
            if o.value - c.value.abs() < Decimal::ZERO {
                out.push(format!(
                    "free cash flow negative in {period} [{}, {}]",
                    o.note, c.note
                ));
            }
        }
    }
    out
}

/// Python memo._rule_line.
fn rule_line(r: &Rule) -> String {
    let where_ = locator_label(r.page, None, None, "pdf", None);
    format!(
        "{}: {} [{} {where_}: \"{}\"]",
        r.label,
        r.value,
        &r.document_id[..8],
        r.quote.trim()
    )
}

fn no_facts(entity: &str) -> String {
    format!("# {entity}\n\nNo verified facts available. Nothing to report.\n")
}

/// Python memo.build_memo (no comps, no legal).
fn render_memo(entity: &str, m: &Memo) -> String {
    if m.lines.is_empty() && m.rules.is_empty() {
        return no_facts(entity);
    }
    let mut out = vec![
        format!("# {entity}: financial summary (draft, analyst review required)"),
        String::new(),
    ];
    out.extend(m.lines.iter().map(|l| format!("- {l}")));
    if !m.derived.is_empty() {
        out.push(String::new());
        out.push("Derived (computed in code):".into());
        out.extend(m.derived.iter().map(|d| format!("- {d}")));
    }
    if !m.rules.is_empty() {
        out.push(String::new());
        out.push("Firm rules applied (accepted, quoted):".into());
        out.extend(m.rules.iter().map(|r| format!("- {}", rule_line(r))));
    }
    if !m.comps.is_empty() {
        out.push(String::new());
        out.push("Trading comps (peers, each cited):".into());
        out.extend(m.comps.iter().map(|c| format!("- {c}")));
    }
    out.push(String::new());
    out.push("Sources:".into());
    out.extend(m.notes.iter().cloned());
    out.join("\n") + "\n"
}

/// Python memo_templates.build_memo_sections.
fn render_sections(
    entity: &str,
    template: &str,
    keys: &[String],
    headings: &Value,
    intro: &str,
    m: &Memo,
) -> String {
    if m.lines.is_empty() && m.rules.is_empty() {
        return no_facts(entity);
    }
    let mut out = vec![format!(
        "# {entity}: {template} memo (draft, analyst review required)"
    )];
    if !intro.is_empty() {
        out.push(String::new());
        out.push(intro.to_string());
    }
    for key in keys {
        let items: Vec<String> = match key.as_str() {
            "financial" => m.lines.iter().map(|l| format!("- {l}")).collect(),
            "derived" => m.derived.iter().map(|d| format!("- {d}")).collect(),
            "risks" => m.risks.iter().map(|r| format!("- {r}")).collect(),
            "rules" => m
                .rules
                .iter()
                .map(|r| format!("- {}: {} [{}]", r.label, r.value, &r.document_id[..8]))
                .collect(),
            _ => Vec::new(),
        };
        if items.is_empty() {
            continue;
        }
        let default = SECTIONS
            .iter()
            .find(|(k, _)| k == key)
            .map_or("", |(_, h)| h);
        let heading = headings
            .get(key.as_str())
            .and_then(Value::as_str)
            .unwrap_or(default);
        out.push(String::new());
        out.push(format!("## {heading}"));
        out.extend(items);
    }
    out.push(String::new());
    out.push("Sources:".into());
    out.extend(m.notes.iter().cloned());
    out.join("\n") + "\n"
}

/// _memo_legal needs the legal module: a request that names a legal_doc goes to FastAPI unchanged.
fn needs_relay(q: &HashMap<String, String>) -> bool {
    q.get("legal_doc").is_some_and(|v| !v.is_empty())
}

/// Python `_memo_comps`: peers and a period, or no comps section at all.
async fn memo_comps(
    tx: &mut Transaction<'_, Postgres>,
    vis: &Visibility,
    m: &mut Memo,
    entity: &str,
    q: &HashMap<String, String>,
) -> Result<(), ApiError> {
    let names: Vec<String> = q
        .get("peers")
        .map(|p| {
            p.split(',')
                .map(str::trim)
                .filter(|n| !n.is_empty())
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default();
    let period = q.get("period").cloned().unwrap_or_default();
    if names.is_empty() || period.is_empty() {
        return Ok(());
    }
    if names.len() > 50 {
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "too many peers",
        ));
    }
    let res = comps::run_revenue(tx, vis, entity, &names, &period).await?;
    add_comps(tx, m, &res).await
}

/// Python memo.add_comps: each peer's EV and multiple cited, then the median and the implied range.
async fn add_comps(
    tx: &mut Transaction<'_, Postgres>,
    m: &mut Memo,
    res: &comps::Comps,
) -> Result<(), ApiError> {
    for p in &res.peers {
        let Some(ev) = &p.ev else {
            m.comps.push(format!(
                "{}: no enterprise value fact, no multiple",
                p.entity
            ));
            continue;
        };
        let n_ev = cite_fact(tx, m, ev).await?;
        let ev_doc = doc_name(tx, &ev.sources[0].doc_id)
            .await?
            .unwrap_or_else(|| "unknown".into());
        let mut parts = vec![format!(
            "EV {} {} [{n_ev}] (EV source: {ev_doc})",
            gloss(ev.value),
            ev.unit
        )];
        match (p.multiple, &p.rev) {
            (Some(mult), Some(rev)) => {
                let n = cite_fact(tx, m, rev).await?;
                parts.push(format!(
                    "EV/revenue {}x [{n}]",
                    comps::quantize_multiple(mult)
                ));
            }
            _ => parts.push(format!(
                "EV/revenue not meaningful: {}",
                p.nm.as_deref().unwrap_or("no multiple")
            )),
        }
        m.comps.push(format!(
            "{} ({}): {}",
            p.entity,
            res.period,
            parts.join("; ")
        ));
    }
    if let Some(median) = res.median {
        m.comps.push(format!(
            "Peer median EV/revenue: {median}x across {} peers (computed in code)",
            res.n
        ));
    }
    match (
        &res.implied.low,
        &res.implied.mid,
        &res.implied.high,
        &res.implied.target,
    ) {
        (Some(low), Some(mid), Some(high), Some(t)) => {
            let n = cite_fact(tx, m, t).await?;
            m.comps.push(format!(
                "Implied EV from revenue {} {}: {low} to {high}, median {mid} [{n}]",
                t.value, t.unit
            ));
        }
        _ => m
            .comps
            .push(format!("Implied range for revenue: {}", res.implied.note)),
    }
    Ok(())
}

/// Python memo._cite_fact: append the fact's first source as a footnote and return its number.
async fn cite_fact(
    tx: &mut Transaction<'_, Postgres>,
    m: &mut Memo,
    f: &comps::FactRec,
) -> Result<i32, ApiError> {
    let n = m.notes.len() as i32 + 1;
    let src = &f.sources[0];
    let filename = doc_name(tx, &src.doc_id)
        .await?
        .unwrap_or_else(|| src.doc_id[..8].to_string());
    let where_ = locator_label(
        src.page,
        src.section.as_deref(),
        src.heading.as_deref(),
        &src.kind,
        src.anchor.as_deref(),
    );
    m.notes.push(format!(
        "[{n}] {filename}, {where_}: \"{}\"",
        src.quote.trim()
    ));
    Ok(n)
}

async fn doc_name(
    tx: &mut Transaction<'_, Postgres>,
    doc_id: &str,
) -> Result<Option<String>, ApiError> {
    let row: Option<(String,)> = sqlx::query_as("SELECT filename FROM document WHERE id = $1")
        .bind(doc_id)
        .fetch_optional(&mut **tx)
        .await?;
    Ok(row.map(|r| r.0))
}

pub async fn get_memo(State(s): State<AppState>, req: Request) -> Result<Response, ApiError> {
    let query = axum::extract::Query::<HashMap<String, String>>::try_from_uri(req.uri()).ok();
    let q = match query {
        Some(Query(q)) if !needs_relay(&q) => q,
        _ => return Ok(proxy::forward(State(s), req).await),
    };
    let headers: HeaderMap = req.headers().clone();
    let (p, mut tx) = principal(&s, &headers).await?;
    let entity = q
        .get("entity")
        .cloned()
        .ok_or_else(|| ApiError::missing_query("entity"))?;
    let vis = Visibility::load(&mut tx, &p).await?;
    let mut m = build_data(&mut tx, &vis, &entity).await?;
    memo_comps(&mut tx, &vis, &mut m, &entity, &q).await?;
    tx.commit().await?;
    let markdown = render_memo(&entity, &m);
    Ok(Json(json!({ "entity": entity, "markdown": markdown })).into_response())
}

pub async fn get_memo_sections(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, ApiError> {
    let (p, mut tx) = principal(&s, &headers).await?;
    let entity = q
        .get("entity")
        .cloned()
        .ok_or_else(|| ApiError::missing_query("entity"))?;
    let template = q.get("template").cloned().unwrap_or_else(|| "ic".into());

    let firm: Vec<(String, String, String, String)> =
        sqlx::query_as("SELECT name, sections, headings, intro FROM memo_template ORDER BY name")
            .fetch_all(&mut *tx)
            .await?;
    let (keys, headings, intro): (Vec<String>, Value, String) =
        if let Some((_, keys)) = BUILT_IN.iter().find(|(n, _)| *n == template) {
            (
                keys.iter().map(|k| k.to_string()).collect(),
                json!({}),
                String::new(),
            )
        } else if let Some((_, sections, headings, intro)) = firm.iter().find(|r| r.0 == template) {
            let keys: Vec<String> = serde_json::from_str(sections).unwrap_or_default();
            let headings: Value = serde_json::from_str(headings).unwrap_or(json!({}));
            (keys, headings, intro.clone())
        } else {
            // Python: sorted(list_templates) names every built-in and firm template.
            let mut names: Vec<String> = BUILT_IN.iter().map(|(n, _)| n.to_string()).collect();
            names.extend(firm.iter().map(|r| r.0.clone()));
            names.sort();
            let listed: Vec<String> = names.iter().map(|n| format!("'{n}'")).collect();
            return Err(ApiError::new(
                axum::http::StatusCode::UNPROCESSABLE_ENTITY,
                format!("unknown template; choose one of [{}]", listed.join(", ")),
            ));
        };

    let vis = Visibility::load(&mut tx, &p).await?;
    let m = build_data(&mut tx, &vis, &entity).await?;
    tx.commit().await?;
    let markdown = render_sections(&entity, &template, &keys, &headings, &intro, &m);
    Ok(Json(
        json!({ "entity": entity, "template": template, "markdown": markdown }),
    ))
}
