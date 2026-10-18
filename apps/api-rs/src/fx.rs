//! Port of the FX path in app/macrodata.py (EcbFxProvider, fx_rate). ECB euro reference rates, newest published day.
//! Cross rates go through EUR and carry the older of the two days. Nothing is filled in for a missing rate: a gap is
//! an Err. Used by comps; no route of its own.
#![allow(dead_code)]

use regex::Regex;
use rust_decimal::Decimal;

const ECB_URL: &str =
    "https://data-api.ecb.europa.eu/service/data/EXR/D.{ccy}.EUR.SP00.A?lastNObservations=5";

#[derive(Debug, Clone, PartialEq)]
pub struct Quote {
    pub price: Decimal,
    pub as_of: String,
    pub source: &'static str,
}

/// (rate, as_of, source) as the Python fx hook returns it.
pub type FxRate = (Decimal, String, &'static str);

fn dec(v: &str, what: &str) -> Result<Decimal, String> {
    v.parse::<Decimal>()
        .map_err(|_| format!("{what}: unreadable value {v:?}"))
}

/// ECB SDMX XML: every <Obs> holds one ObsDimension (day) and one ObsValue (rate). The newest day wins; equal days
/// fall back to the larger value text, as Python's max() over (day, value) pairs does.
pub fn parse_ecb(raw: &str, ccy: &str) -> Result<Quote, String> {
    let obs = Regex::new(r"(?s)<(?:[A-Za-z0-9_]+:)?Obs>(.*?)</(?:[A-Za-z0-9_]+:)?Obs>").unwrap();
    let day_re = Regex::new(r#"ObsDimension[^>]*?value="([^"]*)""#).unwrap();
    let val_re = Regex::new(r#"ObsValue[^>]*?value="([^"]*)""#).unwrap();
    let mut pairs: Vec<(String, String)> = Vec::new();
    for o in obs.captures_iter(raw) {
        let body = &o[1];
        if let (Some(d), Some(v)) = (day_re.captures(body), val_re.captures(body)) {
            pairs.push((d[1].to_string(), v[1].to_string()));
        }
    }
    let (day, value) = pairs
        .into_iter()
        .max()
        .ok_or_else(|| format!("ecb: no observations for {ccy}"))?;
    Ok(Quote {
        price: dec(&value, &format!("ecb {ccy}"))?,
        as_of: day,
        source: "ecb",
    })
}

/// Fetch one currency's EUR quote. Python EcbFxProvider.quote(symbol): symbol is the currency code.
pub async fn quote(http: &reqwest::Client, symbol: &str) -> Result<Quote, String> {
    let ccy = symbol.to_uppercase();
    let url = ECB_URL.replace("{ccy}", &ccy);
    let raw = http
        .get(url)
        .header("Accept", "application/vnd.sdmx.data+xml")
        .header("User-Agent", "pe-ai/0.1")
        .send()
        .await
        .map_err(|e| format!("ecb: {e}"))?
        .text()
        .await
        .map_err(|_| format!("ecb: unreadable answer for {ccy}"))?;
    parse_ecb(&raw, &ccy)
}

/// Units of `to` per one unit of `frm`. Python fx_rate(provider, frm, to).
pub async fn fx_rate(http: &reqwest::Client, frm: &str, to: &str) -> Result<FxRate, String> {
    let (frm, to) = (frm.to_uppercase(), to.to_uppercase());
    if frm == to {
        return Ok((Decimal::ONE, String::new(), "identity"));
    }
    if to == "EUR" {
        let q = quote(http, &frm).await?;
        return Ok((q.price, q.as_of, "ecb"));
    }
    if frm == "EUR" {
        let q = quote(http, &to).await?;
        return Ok((Decimal::ONE / q.price, q.as_of, "ecb"));
    }
    let a = quote(http, &frm).await?;
    let b = quote(http, &to).await?;
    let as_of = if a.as_of <= b.as_of { a.as_of } else { b.as_of };
    Ok((a.price / b.price, as_of, "ecb"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn newest_day_wins_on_saved_ecb_response() {
        let raw = include_str!("../../api/tests/fixtures/macro/ecb_exr_usd_eur.xml");
        let q = parse_ecb(raw, "USD").unwrap();
        assert_eq!(q.as_of, "2026-10-16");
        assert_eq!(q.price, "1.1253".parse::<Decimal>().unwrap());
        assert_eq!(q.source, "ecb");
    }

    #[test]
    fn no_observations_is_an_error() {
        assert!(parse_ecb("<x></x>", "XYZ").is_err());
    }
}
