//! Port of POST /calc/share-ledger (app/shareledger.py). Reconciles issued share totals across SH01/SH02/SH19 events.
//! Anything that fits no rule is listed as unreconciled with the gap. Nothing is guessed or forced.

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
use rust_decimal::Decimal;
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize)]
pub struct EventIn {
    kind: String,
    date: String,
    source: String,
    allotted: Option<Dec>,
    total_after: Option<Dec>,
    old_total: Option<Dec>,
}

#[derive(Deserialize)]
pub struct LedgerIn {
    opening: Dec,
    opening_source: String,
    events: Vec<EventIn>,
}

struct Entry {
    source: String,
    date: String,
    kind: String,
    status: &'static str,
    running_after: Decimal,
    detail: String,
}

struct Ledger {
    entries: Vec<Entry>,
    running: Decimal,
    problems: Vec<String>,
}

fn opt(d: Option<Decimal>) -> String {
    d.map_or("None".into(), |v| v.to_string())
}

impl Ledger {
    fn push(&mut self, source: &str, date: &str, kind: &str, status: &'static str, detail: String) {
        self.entries.push(Entry {
            source: source.into(),
            date: date.into(),
            kind: kind.into(),
            status,
            running_after: self.running,
            detail,
        });
    }

    fn bad(&mut self, e: &EventIn, why: String) {
        self.problems.push(format!("{}: {why}", e.source));
        self.push(&e.source, &e.date, &e.kind, "unreconciled", why);
    }

    fn consolidate(&mut self, e: &EventIn) {
        let total = e.total_after.as_ref().map(|d| d.0);
        let old = e.old_total.as_ref().map(|d| d.0);
        match (old, total) {
            (Some(old), Some(new)) if new > Decimal::ZERO => {
                if old != self.running {
                    self.bad(
                        e,
                        format!(
                            "consolidation starts from {old}, ledger has {}",
                            self.running
                        ),
                    );
                } else if !(old % new).is_zero() {
                    self.bad(e, format!("{old} / {new} is not a whole ratio"));
                } else {
                    self.running = new;
                    // Python prints the ideal exponent of an exact division: old scale minus new scale decimals.
                    let decimals = (old.scale() as i64 - new.scale() as i64).max(0) as u32;
                    let mut ratio = old / new;
                    ratio.rescale(decimals);
                    self.push(
                        &e.source,
                        &e.date,
                        &e.kind,
                        "consolidated",
                        format!("{ratio}-for-1"),
                    );
                }
            }
            _ => self.bad(
                e,
                "consolidation needs old_total and a positive total_after".into(),
            ),
        }
    }

    fn statement(&mut self, e: &EventIn) {
        let total = e.total_after.as_ref().map(|d| d.0);
        if total == Some(self.running) {
            self.push(&e.source, &e.date, &e.kind, "statement_ok", String::new());
        } else {
            let why = format!("states {}, ledger has {}", opt(total), self.running);
            self.bad(e, why);
        }
    }

    fn allot_group(&mut self, base: Decimal, allots: &[&EventIn]) {
        let mut ok: Vec<(&EventIn, Decimal, Decimal)> = Vec::new();
        for e in allots {
            match (e.allotted.as_ref(), e.total_after.as_ref()) {
                (Some(a), Some(t)) => ok.push((e, a.0, t.0)),
                _ => self.bad(e, "allotment needs allotted and total_after".into()),
            }
        }
        let same = ok.iter().filter(|(_, a, t)| *t == base + a).count();
        if ok.len() == 1 && same == 1 {
            let (e, a, _) = ok[0];
            self.running = base + a;
            self.push(&e.source, &e.date, "allot", "cumulative", String::new());
            return;
        }
        if ok.len() > 1 && same == ok.len() {
            self.running = base
                + ok.iter()
                    .map(|(_, a, _)| *a)
                    .fold(Decimal::ZERO, |acc, a| acc + a);
            for (e, _, t) in &ok {
                let detail = format!(
                    "stated {t} against base {base}; combined total {}",
                    self.running
                );
                self.push(&e.source, &e.date, "allot", "same_base", detail);
            }
            return;
        }
        for (e, a, t) in ok {
            let why = format!("states {t}; base {base} + allotted {a} = {}", base + a);
            self.bad(e, why);
        }
    }
}

fn reconcile(opening: Decimal, opening_source: &str, events: &[EventIn]) -> Ledger {
    let mut led = Ledger {
        entries: Vec::new(),
        running: opening,
        problems: Vec::new(),
    };
    led.entries.push(Entry {
        source: opening_source.into(),
        date: String::new(),
        kind: "opening".into(),
        status: "opening",
        running_after: opening,
        detail: String::new(),
    });
    let mut ordered: Vec<&EventIn> = events.iter().collect();
    ordered.sort_by(|a, b| a.date.cmp(&b.date));
    let mut i = 0;
    while i < ordered.len() {
        let day = ordered[i].date.clone();
        let mut j = i;
        while j < ordered.len() && ordered[j].date == day {
            j += 1;
        }
        let group = &ordered[i..j];
        for e in group.iter().filter(|e| e.kind == "statement") {
            led.statement(e);
        }
        let allots: Vec<&EventIn> = group
            .iter()
            .copied()
            .filter(|e| e.kind == "allot")
            .collect();
        if !allots.is_empty() {
            let base = led.running;
            led.allot_group(base, &allots);
        }
        for e in group.iter().filter(|e| e.kind == "consolidate") {
            led.consolidate(e);
        }
        i = j;
    }
    led
}

/// Python date.fromisoformat() message for a bad date: the same wording for the same mistake.
fn check_date(d: &str) -> Result<(), String> {
    if NaiveDate::parse_from_str(d, "%Y-%m-%d").is_ok() {
        return Ok(());
    }
    let b = d.as_bytes();
    let shaped = b.len() == 10
        && b[4] == b'-'
        && b[7] == b'-'
        && b.iter()
            .enumerate()
            .all(|(i, c)| i == 4 || i == 7 || c.is_ascii_digit());
    if shaped {
        let month: u32 = d[5..7].parse().unwrap_or(0);
        if !(1..=12).contains(&month) {
            return Err("month must be in 1..12".into());
        }
        return Err("day is out of range for month".into());
    }
    Err(format!("Invalid isoformat string: '{d}'"))
}

pub async fn calc_share_ledger(
    State(s): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<LedgerIn>,
) -> Result<Json<Value>, ApiError> {
    let (_p, tx) = principal(&s, &headers).await?;
    tx.commit().await?;
    if body
        .events
        .iter()
        .any(|e| !matches!(e.kind.as_str(), "allot" | "statement" | "consolidate"))
        || body.events.len() > 500
    {
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "kind must be allot, statement or consolidate; at most 500 events",
        ));
    }
    for e in &body.events {
        if let Err(why) = check_date(&e.date) {
            return Err(ApiError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                format!("bad date: {why}"),
            ));
        }
    }
    let led = reconcile(body.opening.0, &body.opening_source, &body.events);
    let entries: Vec<Value> = led
        .entries
        .iter()
        .map(|x| {
            json!({
                "source": x.source,
                "date": x.date,
                "kind": x.kind,
                "status": x.status,
                "running_after": x.running_after.to_string(),
                "detail": x.detail,
            })
        })
        .collect();
    Ok(Json(json!({
        "running": led.running.to_string(),
        "problems": led.problems,
        "entries": entries,
    })))
}
