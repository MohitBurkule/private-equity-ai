//! Port of app/citations.py and the pure parts of app/facts.py. Numbers are checked in code, never by a model.

use regex::Regex;
use rust_decimal::Decimal;
use std::str::FromStr;
use std::sync::OnceLock;

/// Same grammar as the Python `_NUM`: a parenthesised figure may hold spaces, as iXBRL tables print "( 747 )".
fn num_re() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| {
        Regex::new(r"\(\s*\$?\s*\d[\d,]*(?:\.\d+)?\s*\)|-?\$?\s*\d[\d,]*(?:\.\d+)?").unwrap()
    })
}

fn loss_re() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| Regex::new(r"(?i)\(loss\)|\bloss\b").unwrap())
}

fn outflow_re() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| {
        Regex::new(r"(?i)capex|capital.?expend|purchase|repay|payment|dividend|distribution|buyback|repurchase|acquisition|outflow|paid")
            .unwrap()
    })
}

/// Labels for money paid out. Their tables print the amount in parentheses, so a positive claim is the same figure.
pub fn is_outflow(metric: &str) -> bool {
    outflow_re().is_match(metric)
}

/// Signed value of a printed number: parentheses or a minus sign mean negative.
fn parse_number(raw: &str) -> Option<Decimal> {
    let s = raw.trim();
    let neg = (s.starts_with('(') && s.ends_with(')')) || s.contains('-');
    let digits: String = s
        .chars()
        .filter(|c| c.is_ascii_digit() || *c == '.')
        .collect();
    if digits.is_empty() || digits == "." {
        return None;
    }
    let v = Decimal::from_str(&digits).ok()?;
    Some(if neg { -v } else { v })
}

fn numbers_in(text: &str) -> impl Iterator<Item = Decimal> + '_ {
    num_re()
        .find_iter(text)
        .filter_map(|m| parse_number(m.as_str()))
}

/// Whitespace-insensitive, case-insensitive substring check.
pub fn quote_in_page(quote: &str, page_text: &str) -> bool {
    let norm = |t: &str| {
        t.split_whitespace()
            .collect::<Vec<_>>()
            .join(" ")
            .to_lowercase()
    };
    let q = norm(quote);
    !q.is_empty() && norm(page_text).contains(&q)
}

/// True if `claimed` (already in output units) equals some number in the span after `scale`.
/// Sign must match the printed sign, except: outflow labels may be asked as positive magnitudes, and a loss may be
/// asked as negative when the quote says "loss" without parentheses.
pub fn verify_number(claimed: Decimal, span_text: &str, scale: Decimal, outflow: bool) -> bool {
    for n in numbers_in(span_text) {
        // checked_mul: an overflowing product cannot equal the claim, so skip it.
        let Some(v) = n.checked_mul(scale) else {
            continue;
        };
        if v == claimed {
            return true;
        }
        if v.abs() != claimed.abs() {
            continue;
        }
        if outflow {
            return true;
        }
        if v > Decimal::ZERO && claimed < Decimal::ZERO && loss_re().is_match(span_text) {
            return true;
        }
    }
    false
}

/// Workbook quotes start with their cell: "P&L!C14: 1,000 | row: Revenue" or "P&L!C14, row: Revenue".
/// Returns (sheet, cell, row label). Rust's regex has no lookahead, so the Python pattern is matched by hand.
pub fn xlsx_location(quote: &str) -> Option<(String, String, Option<String>)> {
    let t = quote.trim();
    let mut sheet_end = None;
    for (i, c) in t.char_indices() {
        // Python's lazy `.+?` takes the first `!` that leaves a valid cell and separator after it.
        if c != '!' || i == 0 {
            continue;
        }
        let rest = &t[i + 1..];
        let letters = rest.chars().take_while(|c| c.is_ascii_uppercase()).count();
        if !(1..=3).contains(&letters) {
            continue;
        }
        let after_letters = &rest[letters..];
        let digits = after_letters
            .chars()
            .take_while(|c| c.is_ascii_digit())
            .count();
        if digits == 0 {
            continue;
        }
        let after_cell = &after_letters[digits..];
        if after_cell.starts_with(": ") || after_cell.starts_with(", row: ") {
            sheet_end = Some((i, letters + digits));
            break;
        }
    }
    let (i, cell_len) = sheet_end?;
    let sheet = &t[..i];
    let cell = &t[i + 1..i + 1 + cell_len];
    let row = Regex::new(r"(?:\| |, )row: (.+)$")
        .unwrap()
        .captures(quote)
        .map(|c| c[1].trim().to_string());
    Some((sheet.to_string(), cell.to_string(), row))
}

/// How a citation is shown to a reader. Mirrors app/citations.py locator_label.
pub fn locator_label(
    page: i32,
    section: Option<&str>,
    heading: Option<&str>,
    kind: &str,
    anchor: Option<&str>,
) -> String {
    if kind == "xlsx" {
        let wh = match (heading, anchor) {
            (Some(h), Some(a)) => format!("{h}!{a}"),
            _ => "workbook".to_string(),
        };
        return match section {
            Some(s) if !s.is_empty() => format!("{wh}, row: {s}"),
            _ => wh,
        };
    }
    if kind == "html" || page == 0 {
        return match section {
            Some(s) if !s.is_empty() => match heading {
                Some(h) => format!("§{s} {h}"),
                None => format!("§{s}"),
            },
            _ => "HTML filing".to_string(),
        };
    }
    format!("p.{page}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parentheses_are_negative() {
        assert_eq!(parse_number("(747)"), Some(Decimal::from(-747)));
        assert_eq!(parse_number("1,000"), Some(Decimal::from(1000)));
    }

    #[test]
    fn quote_match_ignores_whitespace_and_case() {
        assert!(quote_in_page("Net  Income", "...net income was 5"));
        assert!(!quote_in_page("", "anything"));
    }

    #[test]
    fn xlsx_quote_parses_cell_and_row() {
        let (s, c, r) = xlsx_location("P&L!C14: 1,000 | row: Revenue").unwrap();
        assert_eq!(
            (s.as_str(), c.as_str(), r.as_deref()),
            ("P&L", "C14", Some("Revenue"))
        );
        assert!(xlsx_location("no cell here").is_none());
    }

    #[test]
    fn outflow_matches_positive_claim() {
        assert!(verify_number(
            Decimal::from(747),
            "Capex (747)",
            Decimal::ONE,
            true
        ));
        assert!(!verify_number(
            Decimal::from(747),
            "Revenue (747)",
            Decimal::ONE,
            false
        ));
    }
}
