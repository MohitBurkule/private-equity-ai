//! Port of POST /calc/tieout (app/extract/tieout.py tie_out). Places short table rows into columns using the printed
//! column totals. Only a single surviving placement is resolved; anything else is reported, never guessed.

use crate::auth::principal;
use crate::error::ApiError;
use crate::facts::Dec;
use crate::AppState;
use axum::{extract::State, http::HeaderMap, Json};
use rust_decimal::Decimal;
use serde::de::{MapAccess, Visitor};
use serde::{Deserialize, Deserializer};
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, HashMap};
use std::fmt;

const MAX_PLACEMENTS: u128 = 2_000_000;

type Row = (String, Vec<Option<Dec>>);

/// A row of printed values; null is a dash. Labels keep the order they arrive in, as a Python dict does, and a
/// repeated label keeps its first position with its last value.
#[derive(Deserialize)]
pub struct TieOutIn {
    #[serde(deserialize_with = "ordered_rows")]
    rows: Vec<Row>,
    base: Vec<Dec>,
    total: Vec<Dec>,
}

fn ordered_rows<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<Row>, D::Error> {
    struct Rows;
    impl<'de> Visitor<'de> for Rows {
        type Value = Vec<Row>;
        fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
            f.write_str("an object of label to values")
        }
        fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
            let mut out: Vec<Row> = Vec::new();
            while let Some((k, v)) = map.next_entry::<String, Vec<Option<Dec>>>()? {
                match out.iter_mut().find(|(label, _)| *label == k) {
                    Some(slot) => slot.1 = v,
                    None => out.push((k, v)),
                }
            }
            Ok(out)
        }
    }
    d.deserialize_map(Rows)
}

#[derive(PartialEq)]
enum Status {
    Resolved,
    Ambiguous,
    NoSolution,
    TooLarge,
}

impl Status {
    fn name(&self) -> &'static str {
        match self {
            Status::Resolved => "resolved",
            Status::Ambiguous => "ambiguous",
            Status::NoSolution => "no_solution",
            Status::TooLarge => "too_large",
        }
    }
}

struct TieOut {
    status: Status,
    rows: Option<Vec<(String, Vec<Decimal>)>>,
    solutions: u64,
    detail: String,
}

fn stop(status: Status, detail: &str) -> TieOut {
    TieOut {
        status,
        rows: None,
        solutions: 0,
        detail: detail.into(),
    }
}

/// math.comb, saturating so an oversized product is caught by the cap instead of overflowing.
fn comb(n: u128, k: u128) -> u128 {
    let k = k.min(n - k.min(n));
    let mut r: u128 = 1;
    for i in 0..k {
        r = r.saturating_mul(n - i) / (i + 1);
    }
    r
}

/// Index combinations of `k` items from `0..n`, in the order itertools.combinations yields them.
fn combinations(n: usize, k: usize) -> Vec<Vec<usize>> {
    let mut out = Vec::new();
    if k > n {
        return out;
    }
    let mut idx: Vec<usize> = (0..k).collect();
    loop {
        out.push(idx.clone());
        let Some(i) = (0..k).rev().find(|&i| idx[i] != i + n - k) else {
            return out;
        };
        idx[i] += 1;
        for j in i + 1..k {
            idx[j] = idx[j - 1] + 1;
        }
    }
}

/// Map key for a numeric tuple: values equal in number share a key whatever their scale.
fn key(v: &[Decimal]) -> Vec<Decimal> {
    v.iter().map(|d| d.normalize()).collect()
}

/// Distinct column vectors from placing the tokens in order into `ncols` columns (a dash or zero prints as 0),
/// sorted numerically. Numerically equal vectors keep the first representative, as a Python set does.
fn placements(tokens: &[Option<Decimal>], ncols: usize) -> Vec<Vec<Decimal>> {
    let mut seen: BTreeMap<Vec<Decimal>, ()> = BTreeMap::new();
    for pos in combinations(ncols, tokens.len()) {
        let mut v = vec![Decimal::ZERO; ncols];
        for (p, t) in pos.iter().zip(tokens) {
            v[*p] = match t {
                Some(d) if !d.is_zero() => *d,
                _ => Decimal::ZERO,
            };
        }
        seen.entry(v).or_insert(());
    }
    seen.into_keys().collect()
}

fn tie_out(rows: &[Row], base: &[Dec], total: &[Dec]) -> TieOut {
    let n = base.len();
    if total.len() != n {
        return stop(
            Status::NoSolution,
            "base and total have different column counts",
        );
    }
    if rows.iter().any(|(_, t)| t.len() > n) {
        return stop(Status::NoSolution, "a row has more values than columns");
    }
    let mut size: u128 = 1;
    for (_, t) in rows {
        size = size.saturating_mul(comb(n as u128, t.len() as u128));
        if size > MAX_PLACEMENTS {
            return stop(
                Status::TooLarge,
                &format!("more than {MAX_PLACEMENTS} placements to try"),
            );
        }
    }
    let options: Vec<Vec<Vec<Decimal>>> = rows
        .iter()
        .map(|(_, t)| {
            let tokens: Vec<Option<Decimal>> = t.iter().map(|d| d.as_ref().map(|d| d.0)).collect();
            placements(&tokens, n)
        })
        .collect();
    let need: Vec<Decimal> = base.iter().zip(total).map(|(b, t)| t.0 - b.0).collect();

    // Sequential search over rows, keeping each reachable column sum once with its first witness, in insertion order.
    let mut reach: Vec<(Vec<Decimal>, Vec<Vec<Decimal>>)> =
        vec![(vec![Decimal::ZERO; n], Vec::new())];
    for opts in &options {
        let mut seen: HashMap<Vec<Decimal>, ()> = HashMap::new();
        let mut nxt: Vec<(Vec<Decimal>, Vec<Vec<Decimal>>)> = Vec::new();
        for (acc, chosen) in &reach {
            for o in opts {
                let s: Vec<Decimal> = acc.iter().zip(o).map(|(a, b)| a + b).collect();
                if seen.insert(key(&s), ()).is_none() {
                    let mut w = chosen.clone();
                    w.push(o.clone());
                    nxt.push((s, w));
                }
            }
        }
        reach = nxt;
    }
    let need_key = key(&need);
    let Some((_, witness)) = reach.iter().find(|(s, _)| key(s) == need_key) else {
        return stop(
            Status::NoSolution,
            "no placement makes the columns add up to the printed total",
        );
    };
    let count = count_solutions(&options, &need_key, n);
    if count == 1 {
        let resolved = rows
            .iter()
            .zip(witness)
            .map(|((k, _), v)| (k.clone(), v.clone()))
            .collect();
        return TieOut {
            status: Status::Resolved,
            rows: Some(resolved),
            solutions: 1,
            detail: String::new(),
        };
    }
    TieOut {
        status: Status::Ambiguous,
        rows: None,
        solutions: count,
        detail: "more than one placement ties out".into(),
    }
}

/// Number of full placements reaching `need`, counted per distinct partial sum.
fn count_solutions(options: &[Vec<Vec<Decimal>>], need: &[Decimal], n: usize) -> u64 {
    let mut counts: HashMap<Vec<Decimal>, u64> = HashMap::new();
    counts.insert(key(&vec![Decimal::ZERO; n]), 1);
    for opts in options {
        let mut nxt: HashMap<Vec<Decimal>, u64> = HashMap::new();
        for (acc, c) in &counts {
            for o in opts {
                let s: Vec<Decimal> = acc.iter().zip(o).map(|(a, b)| a + b).collect();
                *nxt.entry(key(&s)).or_insert(0) += c;
            }
        }
        counts = nxt;
    }
    counts.get(need).copied().unwrap_or(0)
}

pub async fn calc_tieout(
    State(s): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<TieOutIn>,
) -> Result<Json<Value>, ApiError> {
    let (_p, tx) = principal(&s, &headers).await?;
    tx.commit().await?;
    let r = tie_out(&body.rows, &body.base, &body.total);
    let rows = match r.rows {
        None => Value::Null,
        Some(rows) => Value::Object(
            rows.into_iter()
                .map(|(k, v)| {
                    (
                        k,
                        json!(v.iter().map(|x| x.to_string()).collect::<Vec<_>>()),
                    )
                })
                .collect::<Map<String, Value>>(),
        ),
    };
    Ok(Json(json!({
        "status": r.status.name(),
        "solutions": r.solutions,
        "detail": r.detail,
        "rows": rows,
    })))
}
