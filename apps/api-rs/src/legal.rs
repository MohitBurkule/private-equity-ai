//! Port of app/legal.py (rule-based key terms from NDA, SPA, credit, lease and employment text) and the
//! document-type check from app/flagship.py, for GET /memo's legal_doc section. Pure code, no model.
//! Patterns are fancy-regex because the sentence splitter and several rules use lookaround.

use fancy_regex::{Regex, RegexBuilder};
use std::sync::LazyLock;

const US_STATES: &str = "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming|District of Columbia";
const OTHER_JURISDICTIONS: &str = "England and Wales|Scotland|Ireland|Cayman Islands|Bermuda|British Virgin Islands|Ontario|Quebec|Canada|Hong Kong|Singapore|Japan|Germany|France|Switzerland|Netherlands|Luxembourg|Israel|India|Brazil|Mexico|Spain|Italy";

const CONFIDENCE_SUFFIX: &str = r"(?:US\$|\$|£|€)\s?[\d,]+(?:\.\d+)?(?:\s?(?:million|billion))?";

/// (term, document types it applies to, pattern), in the order Python's TERMS dict lists them.
static TERMS: LazyLock<Vec<(&'static str, &'static [&'static str], Regex)>> = LazyLock::new(|| {
    let governing = format!(
        r"governed\b[^.]{{0,60}}?\b(?:by|under|in accordance with)\b[^.]{{0,120}}?\blaws?\s+(?:\([^)]*\)\s+)?of\s+(?:the\s+)?(?:united states and (?:the\s+)?)?(?:(?:state|commonwealth)\s+of\s+)?((?:{US_STATES}|{OTHER_JURISDICTIONS}))\b"
    );
    let specs: Vec<(&str, &[&str], String)> = vec![
        ("governing_law", &["nda", "spa", "credit", "lease", "employment"], governing),
        ("term_years", &["nda"], r"(?:for a (?:period|term) of|\bterm of)[^.]{0,40}?\b(\w+(?:\s*\(\d+\))?)\s+years?".into()),
        ("confidentiality_survival_years", &["nda"], r"surviv\w*[^.]{0,80}?(\w+(?:\s*\(\d+\))?)\s+years?".into()),
        ("non_solicit_months", &["nda", "spa"], r"(?:non-?solicit\w*|not (?:to )?solicit)[^.]{0,120}?(\d{1,3}|\w+)\s*(?:\(\d+\)\s*)?(?:months?|years?)|(\d{1,3}|\w+)\s*(?:\(\d+\)\s*)?(?:months?|years?)[^.]{0,160}?\bsolicit\b|(?:non-?solicit\w*|not (?:to )?solicit)[^.]{0,120}?((?:first|second|third|fourth|fifth)\s*(?:\(\d+(?:st|nd|rd|th)\)\s*)?anniversary)|((?:first|second|third|fourth|fifth)\s*(?:\(\d+(?:st|nd|rd|th)\)\s*)?anniversary)[^.]{0,200}?\bsolicit\w*".into()),
        ("non_compete_months", &["spa", "employment"], r#"non-?compet\w*[^.]{0,120}?(\d{1,3}|(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|eighteen|twenty-four|thirty-six)\b)(?:-|\s)?(?:\(\d+\)\s*)?(?:months?|years?)|(\d{1,3}|(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|eighteen|twenty-four|thirty-six)\b)(?:-|\s)?(?:\(\d+\)\s*)?(?:months?|years?)[^.]{0,120}?\(the [“"]?non-?compet\w*\s+period"#.into()),
        ("assignment", &["lease", "employment"], r#"((?:may not|shall not|not be entitled to|no party may)(?! be deemed| be required)[^.]{0,60}?\bassign\w*|\bassign\w*[^.]{0,120}?without the (?:prior )?(?:written )?consent|\bnot (?:be )?assignable\b)"#.into()),
        ("termination_notice_days", &["lease", "employment"], r"(?:terminat|resign)\w*(?![^.]{0,80}\b(?:service|within)\b)[^.]{0,80}?\(?(\d{1,3})\)?\s*days(?:['’]|’s)?\s*(?:(?:prior|advance|written) )*notice|\(?(\d{1,3})\)?\s*days(?:['’]|’s)?\s*(?:(?:prior|advance|written) )*notice(?![^.]*\bservice\b)[^.]{0,80}?(?:terminat|resign)\w*|notice of termination[^.]{0,60}?\(?(\d{1,3})\)?\s*days|(?:terminat|resign)\w*[^.]{0,120}?\(?(\d{1,3})\)?\s*days after the giving of (?:such|the) notice".into()),
        ("severance", &["employment"], r"(severance)".into()),
        ("purchase_price", &["spa"], format!(r"purchase price[^.]{{0,80}}?({CONFIDENCE_SUFFIX})")),
        ("escrow", &["spa"], format!(r"escrow[^.]{{0,100}}?({CONFIDENCE_SUFFIX}|\d+(?:\.\d+)?%)")),
        ("indemnity_cap", &["spa"], format!(r"(?:cap|aggregate liability|maximum liability)[^.]{{0,120}}?({CONFIDENCE_SUFFIX}|\d+(?:\.\d+)?%)")),
        ("basket", &["spa"], format!(r"(?:basket|deductible)[^.]{{0,100}}?({CONFIDENCE_SUFFIX}|\d+(?:\.\d+)?%)")),
        ("termination_fee", &["spa"], format!(r#"(?:reverse )?termination fee(?:(?!exceed)[^.]){{0,120}}?({CONFIDENCE_SUFFIX})|({CONFIDENCE_SUFFIX})[^.]{{0,60}}?\(the [“"]?(?:reverse )?termination fee"#)),
        ("material_adverse_effect", &["spa", "credit"], r"(material adverse (?:effect|change))".into()),
        ("change_of_control", &["spa", "credit", "lease", "employment"], r"(change (?:of|in) control)".into()),
        ("max_leverage", &["credit"], r"(?:leverage ratio|total net leverage)[^.]{0,160}?(\d+(?:\.\d+)?)\s*(?:to|:)\s*(?:1\.00|1(?:\.0)?)".into()),
        ("min_interest_coverage", &["credit"], r"(?:interest coverage|fixed charge coverage)[^.]{0,160}?(\d+(?:\.\d+)?)\s*(?:to|:)\s*(?:1\.00|1(?:\.0)?)".into()),
        ("margin", &["credit"], r"(?:applicable margin|margin)[^.]{0,120}?(\d+(?:\.\d+)?%|\d{2,3}\s*basis points)".into()),
        ("maturity", &["credit"], r"(?:maturity date|matures?)[^.]{0,80}?((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})".into()),
    ];
    specs
        .into_iter()
        .map(|(term, docs, pat)| {
            let rx = RegexBuilder::new(&pat)
                .case_insensitive(true)
                .build()
                .expect("legal pattern compiles");
            (term, docs, rx)
        })
        .collect()
});

static NEG: LazyLock<Regex> = LazyLock::new(|| {
    RegexBuilder::new(r"\b(?:not|no|nothing|neither|nor|except|unless|without)\b")
        .case_insensitive(true)
        .build()
        .expect("negation pattern compiles")
});
static SENT: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?<=[.;])\s+(?=[A-Z(\d])").expect("sentence pattern compiles"));
static WS: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\s+").expect("whitespace pattern compiles"));
static PAREN_NUM: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\((\d+(?:\.\d+)?)\)").expect("number pattern compiles"));
static MOD_WORDS: LazyLock<Regex> = LazyLock::new(|| {
    RegexBuilder::new(r"\b(?:reduc|modif|waiv)\w*")
        .case_insensitive(true)
        .build()
        .expect("amendment pattern compiles")
});
static YEARS_WORD: LazyLock<Regex> = LazyLock::new(|| {
    RegexBuilder::new(r"\byears?\b")
        .case_insensitive(true)
        .build()
        .expect("years pattern compiles")
});
static INSTEAD: LazyLock<Regex> = LazyLock::new(|| {
    RegexBuilder::new(r"\binstead of\b|\bthereafter\b")
        .case_insensitive(true)
        .build()
        .expect("fee pattern compiles")
});

fn has(rx: &Regex, text: &str) -> bool {
    rx.is_match(text).unwrap_or(false)
}

/// One term found in a sentence of a page (python Finding).
#[derive(Clone)]
pub struct Finding {
    pub term: &'static str,
    pub value: String,
    pub page: i32,
    pub quote: String,
    pub needs_review: bool,
}

pub struct Extract {
    pub findings: Vec<Finding>,
    pub absent: Vec<&'static str>,
}

const NUMBER_WORDS: [(&str, i64); 16] = [
    ("one", 1),
    ("two", 2),
    ("three", 3),
    ("four", 4),
    ("five", 5),
    ("six", 6),
    ("seven", 7),
    ("eight", 8),
    ("nine", 9),
    ("ten", 10),
    ("eleven", 11),
    ("twelve", 12),
    ("eighteen", 18),
    ("twenty", 20),
    ("twenty-four", 24),
    ("thirty-six", 36),
];
const ORDINAL_YEARS: [(&str, i64); 5] = [
    ("first", 1),
    ("second", 2),
    ("third", 3),
    ("fourth", 4),
    ("fifth", 5),
];

fn lookup(table: &[(&str, i64)], key: &str) -> Option<i64> {
    table.iter().find(|(k, _)| *k == key).map(|(_, v)| *v)
}

/// python _months: a non-solicit period in months; "four (4) years" becomes 48.
fn months(value: &str, matched: &str) -> String {
    if value.to_lowercase().contains("anniversary") {
        let first = value.split_whitespace().next().unwrap_or("").to_lowercase();
        return match lookup(&ORDINAL_YEARS, &first) {
            Some(n) => (n * 12).to_string(),
            None => value.to_string(),
        };
    }
    let n = if !value.is_empty() && value.chars().all(|c| c.is_ascii_digit()) {
        value.parse::<i64>().ok()
    } else {
        lookup(&NUMBER_WORDS, &value.to_lowercase())
    };
    match n {
        None => value.to_string(),
        Some(n) if has(&YEARS_WORD, matched) => (n * 12).to_string(),
        Some(n) => n.to_string(),
    }
}

/// python extract(): pages are (number, text); doc_type is nda, spa, credit, lease or employment.
pub fn extract(pages: &[(i32, String)], doc_type: &str) -> Extract {
    let mut found = Vec::new();
    let mut absent = Vec::new();
    for (term, docs, rx) in TERMS.iter() {
        if !docs.contains(&doc_type) {
            continue;
        }
        let mut hits = 0;
        for (num, text) in pages {
            let flat = WS.replace_all(text, " ").into_owned();
            let mut sentences = Vec::new();
            let mut last = 0;
            for m in SENT.find_iter(&flat).flatten() {
                sentences.push(&flat[last..m.start()]);
                last = m.end();
            }
            sentences.push(&flat[last..]);
            for sent in sentences {
                let Ok(Some(caps)) = rx.captures(sent) else {
                    continue;
                };
                hits += 1;
                let whole = caps.get(0).map(|m| m.as_str()).unwrap_or("");
                let mut value = (1..caps.len())
                    .filter_map(|i| caps.get(i).map(|m| m.as_str()))
                    .find(|g| !g.is_empty())
                    .unwrap_or("")
                    .trim()
                    .to_string();
                if *term == "non_solicit_months" || *term == "non_compete_months" {
                    value = months(&value, whole);
                }
                if *term == "non_compete_months" && has(&MOD_WORDS, sent) {
                    continue; // an amendment changing the covenant, not the covenant itself
                }
                let review = has(&NEG, sent)
                    || *term == "termination_notice_days"
                    || (*term == "termination_fee" && has(&INSTEAD, sent));
                found.push(Finding {
                    term,
                    value,
                    page: *num,
                    quote: sent.trim().to_string(),
                    needs_review: review,
                });
            }
        }
        if hits == 0 {
            absent.push(*term);
        }
    }
    Extract {
        findings: found,
        absent,
    }
}

/// Python PLAYBOOK check kinds.
enum Check {
    Present,
    Absent,
    Max(f64),
    Min(f64),
}

struct Rule {
    id: &'static str,
    term: &'static str,
    check: Check,
    severity: &'static str,
    text: &'static str,
}

const PLAYBOOK: [Rule; 10] = [
    Rule {
        id: "coc_present",
        term: "change_of_control",
        check: Check::Present,
        severity: "high",
        text: "Change-of-control language: check consent, termination and payment rights.",
    },
    Rule {
        id: "gov_law_absent",
        term: "governing_law",
        check: Check::Absent,
        severity: "medium",
        text: "No governing law stated.",
    },
    Rule {
        id: "non_solicit_long",
        term: "non_solicit_months",
        check: Check::Max(24.0),
        severity: "medium",
        text: "Non-solicit longer than the playbook limit of 24 months.",
    },
    Rule {
        id: "survival_long",
        term: "confidentiality_survival_years",
        check: Check::Max(5.0),
        severity: "medium",
        text: "Confidentiality survival longer than the playbook limit of 5 years.",
    },
    Rule {
        id: "leverage_loose",
        term: "max_leverage",
        check: Check::Max(5.0),
        severity: "high",
        text: "Maximum leverage looser than the playbook limit of 5.00x.",
    },
    Rule {
        id: "coverage_tight",
        term: "min_interest_coverage",
        check: Check::Min(2.0),
        severity: "high",
        text: "Minimum interest cover tighter than the playbook floor of 2.00x.",
    },
    Rule {
        id: "assignment_restricted",
        term: "assignment",
        check: Check::Present,
        severity: "medium",
        text: "Assignment restricted: check consent, change-of-control and transfer rights.",
    },
    Rule {
        id: "employment_non_compete_long",
        term: "non_compete_months",
        check: Check::Max(12.0),
        severity: "medium",
        text: "Non-compete longer than the playbook limit of 12 months.",
    },
    Rule {
        id: "termination_notice_short",
        term: "termination_notice_days",
        check: Check::Min(30.0),
        severity: "medium",
        text: "Termination notice shorter than the playbook floor of 30 days.",
    },
    Rule {
        id: "severance_present",
        term: "severance",
        check: Check::Present,
        severity: "review",
        text: "Severance language: check amount, trigger and release conditions.",
    },
];

/// One red flag. Absent-term flags have no value, page or quote (python None). The memo reads text, page and quote;
/// the rest mirror the python dict.
#[allow(dead_code)]
pub struct Flag {
    pub rule: &'static str,
    pub severity: &'static str,
    pub text: &'static str,
    pub term: &'static str,
    pub value: Option<String>,
    pub page: Option<i32>,
    pub quote: Option<String>,
}

/// python _number: "five (5)" -> 5, "12" -> 12, "five" -> 5; anything else is None so the rule abstains.
fn number(value: &str) -> Option<f64> {
    if let Some(c) = PAREN_NUM.captures(value).ok().flatten() {
        return c.get(1).and_then(|m| m.as_str().parse::<f64>().ok());
    }
    if let Ok(v) = value.parse::<f64>() {
        return Some(v);
    }
    lookup(&NUMBER_WORDS, &value.to_lowercase()).map(|n| n as f64)
}

/// python red_flags(): playbook rules over the findings, then a review flag for each negated sentence.
pub fn red_flags(res: &Extract) -> Vec<Flag> {
    let mut flags = Vec::new();
    for rule in PLAYBOOK.iter() {
        let hits: Vec<&Finding> = res
            .findings
            .iter()
            .filter(|f| f.term == rule.term)
            .collect();
        match rule.check {
            Check::Absent => {
                if res.absent.contains(&rule.term) {
                    flags.push(Flag {
                        rule: rule.id,
                        severity: rule.severity,
                        text: rule.text,
                        term: rule.term,
                        value: None,
                        page: None,
                        quote: None,
                    });
                }
            }
            Check::Present => {
                for f in hits {
                    flags.push(flag_of(rule, f));
                }
            }
            Check::Max(limit) | Check::Min(limit) => {
                let is_max = matches!(rule.check, Check::Max(_));
                for f in hits {
                    let Some(num) = number(&f.value) else {
                        continue;
                    };
                    let breached = if is_max { num > limit } else { num < limit };
                    if breached {
                        flags.push(flag_of(rule, f));
                    }
                }
            }
        }
    }
    for f in res.findings.iter().filter(|f| f.needs_review) {
        flags.push(Flag {
            rule: "negation_review",
            severity: "review",
            text: "Sentence contains a negation word; a person must read it.",
            term: f.term,
            value: Some(f.value.clone()),
            page: Some(f.page),
            quote: Some(f.quote.clone()),
        });
    }
    flags
}

fn flag_of(rule: &Rule, f: &Finding) -> Flag {
    Flag {
        rule: rule.id,
        severity: rule.severity,
        text: rule.text,
        term: rule.term,
        value: Some(f.value.clone()),
        page: Some(f.page),
        quote: Some(f.quote.clone()),
    }
}

/// python flagship.detect_doc_type: a type is named only when exactly one type's marker appears on the first pages.
pub fn detect_doc_type(pages: &[(i32, String)]) -> Option<&'static str> {
    const MARKERS: [(&str, &[&str]); 5] = [
        (
            "credit",
            &["credit agreement", "term loan", "revolving credit"],
        ),
        (
            "spa",
            &[
                "stock purchase agreement",
                "asset purchase agreement",
                "merger agreement",
            ],
        ),
        (
            "nda",
            &[
                "non-disclosure agreement",
                "confidentiality agreement",
                "mutual nondisclosure",
            ],
        ),
        ("lease", &["lease agreement", "commercial lease"]),
        (
            "employment",
            &["employment agreement", "executive employment"],
        ),
    ];
    let head = pages
        .iter()
        .take(3)
        .map(|(_, t)| t.as_str())
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase();
    let hits: Vec<&str> = MARKERS
        .iter()
        .filter(|(_, words)| words.iter().any(|w| head.contains(w)))
        .map(|(t, _)| *t)
        .collect();
    if hits.len() == 1 {
        Some(hits[0])
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nda_governing_law_is_found() {
        let text = "Mutual Non-Disclosure Agreement between the parties. This Agreement shall be governed by the laws of \
                    the State of Delaware. The obligations of confidentiality survive for seven (7) years.";
        let res = extract(&[(1, text.to_string())], "nda");
        let terms: Vec<(&str, &str)> = res
            .findings
            .iter()
            .map(|f| (f.term, f.value.as_str()))
            .collect();
        assert!(
            terms.contains(&("governing_law", "Delaware")),
            "findings: {terms:?}, absent: {:?}",
            res.absent
        );
    }

    #[test]
    fn nda_non_solicit_counts_years_in_months() {
        let text = "Each party will not solicit employees for a period of four (4) years.";
        let res = extract(&[(1, text.to_string())], "nda");
        let found: Vec<(&str, &str)> = res
            .findings
            .iter()
            .map(|f| (f.term, f.value.as_str()))
            .collect();
        assert!(
            found.contains(&("non_solicit_months", "48")),
            "findings: {found:?}"
        );
    }
}
