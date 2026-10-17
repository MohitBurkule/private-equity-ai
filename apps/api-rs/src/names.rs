//! Port of normalise (app/seen_before.py): company-name key used to match a target to an MNPI deal.

use regex::Regex;
use std::sync::OnceLock;

fn suffix() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"\b(incorporated|inc|corporation|corp|company|co|limited|ltd|plc|llc|lp|llp|gmbh|sa|holdings|group)\b")
            .expect("static regex")
    })
}

fn junk() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"[^a-z0-9 ]+").expect("static regex"))
}

pub fn normalise(name: &str) -> String {
    let lower = name.to_lowercase();
    let s = junk().replace_all(&lower, " ").into_owned();
    let s = suffix().replace_all(&s, " ");
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

#[cfg(test)]
mod tests {
    use super::normalise;

    #[test]
    fn drops_punctuation_and_legal_suffixes() {
        assert_eq!(normalise("Acme Holdings, Inc."), "acme");
        assert_eq!(normalise("Foo-Bar Co"), "foo bar");
        assert_eq!(normalise("Group Co"), "");
        assert_eq!(normalise("  Widgets   LLC "), "widgets");
    }
}
