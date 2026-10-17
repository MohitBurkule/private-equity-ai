"""Rule-based key-term extraction from legal text (NDA, SPA, credit agreement). Pure code, no LLM.

Each finding is the exact sentence from a page, so a reviewer can open it. A term not found is listed under
`absent` and never guessed. Patterns find candidates; they do not interpret: a clause that says the opposite
of the pattern's usual reading (e.g. "no non-compete") still matches and needs a human, so findings carry
`needs_review: True` when the sentence contains a negation word.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NEG = re.compile(
    r"\b(?:not|no|nothing|neither|nor|except|unless|without)\b", re.IGNORECASE
)
_SENT = re.compile(r"(?<=[.;])\s+(?=[A-Z(\d])")

# Jurisdictions a governing-law clause can name. The capture is limited to these, so a bare mention of a place
# (a party's address, a court venue) never becomes the governing law.
US_STATES = (
    "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|"
    "Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|"
    "Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|"
    "Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|"
    "West Virginia|Wisconsin|Wyoming|District of Columbia"
)
OTHER_JURISDICTIONS = (
    "England and Wales|Scotland|Ireland|Cayman Islands|Bermuda|British Virgin Islands|Ontario|Quebec|Canada|"
    "Hong Kong|Singapore|Japan|Germany|France|Switzerland|Netherlands|Luxembourg|Israel|India|Brazil|Mexico|Spain|Italy"
)
GOVERNING_LAW_RE = (
    r"governed\b[^.]{0,60}?\b(?:by|under|in accordance with)\b[^.]{0,120}?\blaws?\s+(?:\([^)]*\)\s+)?of\s+(?:the\s+)?(?:united states and (?:the\s+)?)?(?:(?:state|commonwealth)\s+of\s+)?"
    r"((?:" + US_STATES + "|" + OTHER_JURISDICTIONS + r"))\b"
)

TERMS: dict[str, dict] = {
    "governing_law": {
        "doc": ("nda", "spa", "credit", "lease", "employment"),
        "re": GOVERNING_LAW_RE,  # matched case-insensitively, so "Laws of the State of Delaware" counts
    },
    "term_years": {
        "doc": ("nda",),
        "re": r"(?:for a (?:period|term) of|\bterm of)[^.]{0,40}?\b(\w+(?:\s*\(\d+\))?)\s+years?",
    },
    "confidentiality_survival_years": {
        "doc": ("nda",),
        "re": r"surviv\w*[^.]{0,80}?(\w+(?:\s*\(\d+\))?)\s+years?",
    },
    "non_solicit_months": {
        "doc": ("nda", "spa"),
        "re": r"(?:non-?solicit\w*|not (?:to )?solicit)[^.]{0,120}?(\d{1,3}|\w+)\s*(?:\(\d+\)\s*)?(?:months?|years?)|(\d{1,3}|\w+)\s*(?:\(\d+\)\s*)?(?:months?|years?)[^.]{0,160}?\bsolicit\b|(?:non-?solicit\w*|not (?:to )?solicit)[^.]{0,120}?((?:first|second|third|fourth|fifth)\s*(?:\(\d+(?:st|nd|rd|th)\)\s*)?anniversary)",
    },
    "non_compete_months": {
        "doc": ("spa", "employment"),
        "re": r'non-?compet\w*[^.]{0,120}?(\d{1,3}|(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|eighteen|twenty-four|thirty-six)\b)(?:-|\s)?(?:\(\d+\)\s*)?(?:months?|years?)|(\d{1,3}|(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|eighteen|twenty-four|thirty-six)\b)(?:-|\s)?(?:\(\d+\)\s*)?(?:months?|years?)[^.]{0,120}?\(the [“"]?non-?compet\w*\s+period',
    },
    "assignment": {
        "doc": ("lease", "employment"),
        "re": r"((?:may not|shall not|not be entitled to|no party may)(?! be deemed| be required)[^.]{0,60}?\bassign\w*|\bassign\w*[^.]{0,120}?without the (?:prior )?(?:written )?consent|\bnot (?:be )?assignable\b)",
    },
    "termination_notice_days": {
        "doc": ("lease", "employment"),
        "re": r"(?:terminat|resign)\w*(?![^.]{0,80}\b(?:service|within)\b)[^.]{0,80}?\(?(\d{1,3})\)?\s*days(?:['’]|’s)?\s*(?:(?:prior|advance|written) )*notice|\(?(\d{1,3})\)?\s*days(?:['’]|’s)?\s*(?:(?:prior|advance|written) )*notice(?![^.]*\bservice\b)[^.]{0,80}?(?:terminat|resign)\w*|notice of termination[^.]{0,60}?\(?(\d{1,3})\)?\s*days",
    },
    "severance": {
        "doc": ("employment",),
        "re": r"(severance)",
    },
    "purchase_price": {
        "doc": ("spa",),
        "re": r"purchase price[^.]{0,80}?((?:US\$|\$|£|€)\s?[\d,]+(?:\.\d+)?(?:\s?(?:million|billion))?)",
    },
    "escrow": {
        "doc": ("spa",),
        "re": r"escrow[^.]{0,100}?((?:US\$|\$|£|€)\s?[\d,]+(?:\.\d+)?(?:\s?(?:million|billion))?|\d+(?:\.\d+)?%)",
    },
    "indemnity_cap": {
        "doc": ("spa",),
        "re": r"(?:cap|aggregate liability|maximum liability)[^.]{0,120}?((?:US\$|\$|£|€)\s?[\d,]+(?:\.\d+)?(?:\s?(?:million|billion))?|\d+(?:\.\d+)?%)",
    },
    "basket": {
        "doc": ("spa",),
        "re": r"(?:basket|deductible)[^.]{0,100}?((?:US\$|\$|£|€)\s?[\d,]+(?:\.\d+)?(?:\s?(?:million|billion))?|\d+(?:\.\d+)?%)",
    },
    "termination_fee": {
        "doc": ("spa",),
        "re": r'(?:reverse )?termination fee(?:(?!exceed)[^.]){0,120}?((?:US\$|\$|£|€)\s?[\d,]+(?:\.\d+)?(?:\s?(?:million|billion))?)|((?:US\$|\$|£|€)\s?[\d,]+(?:\.\d+)?(?:\s?(?:million|billion))?)[^.]{0,60}?\(the [“"]?(?:reverse )?termination fee',
    },
    "material_adverse_effect": {
        "doc": ("spa", "credit"),
        "re": r"(material adverse (?:effect|change))",
    },
    "change_of_control": {
        "doc": ("spa", "credit", "lease", "employment"),
        "re": r"(change (?:of|in) control)",
    },
    "max_leverage": {
        "doc": ("credit",),
        "re": r"(?:leverage ratio|total net leverage)[^.]{0,160}?(\d+(?:\.\d+)?)\s*(?:to|:)\s*(?:1\.00|1(?:\.0)?)",
    },
    "min_interest_coverage": {
        "doc": ("credit",),
        "re": r"(?:interest coverage|fixed charge coverage)[^.]{0,160}?(\d+(?:\.\d+)?)\s*(?:to|:)\s*(?:1\.00|1(?:\.0)?)",
    },
    "margin": {
        "doc": ("credit",),
        "re": r"(?:applicable margin|margin)[^.]{0,120}?(\d+(?:\.\d+)?%|\d{2,3}\s*basis points)",
    },
    "maturity": {
        "doc": ("credit",),
        "re": r"(?:maturity date|matures?)[^.]{0,80}?((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})",
    },
}


@dataclass
class Finding:
    term: str
    value: str
    page: int
    quote: str
    needs_review: bool


NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "eighteen": 18, "twenty": 20, "twenty-four": 24,
                "thirty-six": 36}
ORDINAL_YEARS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}


def _months(value: str, matched: str) -> str:
    """A non-solicit period in months: '4 years' and 'four (4) years' become 48."""
    if "anniversary" in value.lower():  # "second (2nd) anniversary" of closing: two years
        n = ORDINAL_YEARS.get(value.split()[0].lower())
        return str(n * 12) if n else value
    n = int(value) if value.isdigit() else NUMBER_WORDS.get(value.lower())
    if n is None:
        return value
    return str(n * 12) if re.search(r"\byears?\b", matched, re.IGNORECASE) else str(n)


def extract(pages: list[tuple[int, str]], doc_type: str) -> dict:
    """pages: (number, text). doc_type: nda | spa | credit. Returns findings and absent term names."""
    if doc_type not in ("nda", "spa", "credit", "lease", "employment"):
        raise ValueError("doc_type must be nda, spa, credit, lease or employment")
    found: list[Finding] = []
    absent = []
    for term, spec in TERMS.items():
        if doc_type not in spec["doc"]:
            continue
        rx = re.compile(
            spec["re"], re.IGNORECASE
        )
        hits = 0
        for num, text in pages:
            flat = re.sub(r"\s+", " ", text)
            for sent in _SENT.split(flat):
                m = rx.search(sent)
                if m:
                    hits += 1
                    value = next(g for g in m.groups() if g).strip()
                    if term in ("non_solicit_months", "non_compete_months"):
                        value = _months(value, m.group(0))
                    if term == "non_compete_months" and re.search(r"\b(?:reduc|modif|waiv)\w*", sent, re.IGNORECASE):
                        continue  # an amendment changing the covenant, not the covenant itself
                    review = bool(_NEG.search(sent)) or (term == "termination_fee" and bool(
                        re.search(r"\binstead of\b|\bthereafter\b", sent, re.IGNORECASE)))  # conditional fee change
                    found.append(
                        Finding(
                            term,
                            value,
                            num,
                            sent.strip(),
                            review,
                        )
                    )
        if not hits:
            absent.append(term)
    return {
        "doc_type": doc_type,
        "findings": [f.__dict__ for f in found],
        "absent": absent,
    }


# Firm playbook: each rule fires on extracted findings and cites the sentence that triggered it.
# Rules are data, so a firm can edit limits without touching code. Severity: high | medium | review.
PLAYBOOK: list[dict] = [
    {
        "id": "coc_present",
        "term": "change_of_control",
        "check": "present",
        "severity": "high",
        "text": "Change-of-control language: check consent, termination and payment rights.",
    },
    {
        "id": "gov_law_absent",
        "term": "governing_law",
        "check": "absent",
        "severity": "medium",
        "text": "No governing law stated.",
    },
    {
        "id": "non_solicit_long",
        "term": "non_solicit_months",
        "check": "max",
        "limit": 24,
        "severity": "medium",
        "text": "Non-solicit longer than the playbook limit of 24 months.",
    },
    {
        "id": "survival_long",
        "term": "confidentiality_survival_years",
        "check": "max",
        "limit": 5,
        "severity": "medium",
        "text": "Confidentiality survival longer than the playbook limit of 5 years.",
    },
    {
        "id": "leverage_loose",
        "term": "max_leverage",
        "check": "max",
        "limit": 5.0,
        "severity": "high",
        "text": "Maximum leverage looser than the playbook limit of 5.00x.",
    },
    {
        "id": "coverage_tight",
        "term": "min_interest_coverage",
        "check": "min",
        "limit": 2.0,
        "severity": "high",
        "text": "Minimum interest cover tighter than the playbook floor of 2.00x.",
    },
    {
        "id": "assignment_restricted",
        "term": "assignment",
        "check": "present",
        "severity": "medium",
        "text": "Assignment restricted: check consent, change-of-control and transfer rights.",
    },
    {
        "id": "employment_non_compete_long",
        "term": "non_compete_months",
        "check": "max",
        "limit": 12,
        "severity": "medium",
        "text": "Non-compete longer than the playbook limit of 12 months.",
    },
    {
        "id": "termination_notice_short",
        "term": "termination_notice_days",
        "check": "min",
        "limit": 30,
        "severity": "medium",
        "text": "Termination notice shorter than the playbook floor of 30 days.",
    },
    {
        "id": "severance_present",
        "term": "severance",
        "check": "present",
        "severity": "review",
        "text": "Severance language: check amount, trigger and release conditions.",
    },
]


_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
    "eighteen": 18,
    "twenty": 20,
    "thirty": 30,
    "thirty-six": 36,
}


def _number(value: str) -> float | None:
    """'five (5)' -> 5, '12' -> 12, 'five' -> 5. Anything else -> None, so the rule abstains."""
    m = re.search(r"\((\d+(?:\.\d+)?)\)", value)
    if m:
        return float(m.group(1))
    try:
        return float(value)
    except ValueError:
        return float(_WORDS[value.lower()]) if value.lower() in _WORDS else None


def red_flags(result: dict) -> list[dict]:
    """Apply PLAYBOOK to an extract() result. Abstains on non-numeric values; never guesses a number."""
    flags = []
    by_term: dict[str, list[dict]] = {}
    for f in result["findings"]:
        by_term.setdefault(f["term"], []).append(f)
    for rule in PLAYBOOK:
        term = rule["term"]
        hits = by_term.get(term, [])
        if rule["check"] == "absent":
            if term in result["absent"]:
                flags.append(
                    {
                        "rule": rule["id"],
                        "severity": rule["severity"],
                        "text": rule["text"],
                        "term": term,
                        "value": None,
                        "page": None,
                        "quote": None,
                    }
                )
            continue
        if rule["check"] == "present":
            for f in hits:
                flags.append(
                    {
                        "rule": rule["id"],
                        "severity": rule["severity"],
                        "text": rule["text"],
                        "term": term,
                        "value": f["value"],
                        "page": f["page"],
                        "quote": f["quote"],
                    }
                )
            continue
        for f in hits:
            num = _number(f["value"])
            if num is None:
                continue
            breached = (
                num > rule["limit"] if rule["check"] == "max" else num < rule["limit"]
            )
            if breached:
                flags.append(
                    {
                        "rule": rule["id"],
                        "severity": rule["severity"],
                        "text": rule["text"],
                        "term": term,
                        "value": f["value"],
                        "page": f["page"],
                        "quote": f["quote"],
                    }
                )
    for f in result["findings"]:
        if f["needs_review"]:
            flags.append(
                {
                    "rule": "negation_review",
                    "severity": "review",
                    "text": "Sentence contains a negation word; a person must read it.",
                    "term": f["term"],
                    "value": f["value"],
                    "page": f["page"],
                    "quote": f["quote"],
                }
            )
    return flags
