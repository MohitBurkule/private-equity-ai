"""Rule-based key-term extraction from legal text (NDA, SPA, credit agreement). Pure code, no LLM.

Each finding is the exact sentence from a page, so a reviewer can open it. A term not found is listed under
`absent` and never guessed. Patterns find candidates; they do not interpret: a clause that says the opposite
of the pattern's usual reading (e.g. "no non-compete") still matches and needs a human, so findings carry
`needs_review: True` when the sentence contains a negation word.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_NEG = re.compile(r"\b(?:not|no|nothing|neither|nor|except|unless|without)\b", re.IGNORECASE)
_SENT = re.compile(r"(?<=[.;])\s+(?=[A-Z(\d])")

TERMS: dict[str, dict] = {
    "governing_law": {"doc": ("nda", "spa", "credit"),
                      "re": r"governed by[^.]{0,80}?laws? of (?:the )?([A-Z][A-Za-z ,]{2,60}?)(?:[,.;]| without| and)"},
    "term_years": {"doc": ("nda",), "re": r"(?:for a (?:period|term) of|\bterm of)[^.]{0,40}?\b(\w+(?:\s*\(\d+\))?)\s+years?"},
    "confidentiality_survival_years": {"doc": ("nda",),
                                       "re": r"surviv\w*[^.]{0,80}?(\w+(?:\s*\(\d+\))?)\s+years?"},
    "non_solicit_months": {"doc": ("nda", "spa"), "re": r"(?:non-?solicit\w*|not (?:to )?solicit)[^.]{0,120}?(\d{1,3}|\w+)\s*(?:\(\d+\)\s*)?months?"},
    "non_compete_months": {"doc": ("spa",), "re": r"non-?compet\w*[^.]{0,120}?(\d{1,3}|\w+)\s*(?:\(\d+\)\s*)?(?:months?|years?)"},
    "purchase_price": {"doc": ("spa",), "re": r"purchase price[^.]{0,80}?((?:US\$|\$|£|€)\s?[\d,]+(?:\.\d+)?(?:\s?(?:million|billion))?)"},
    "escrow": {"doc": ("spa",), "re": r"escrow[^.]{0,100}?((?:US\$|\$|£|€)\s?[\d,]+(?:\.\d+)?(?:\s?(?:million|billion))?|\d+(?:\.\d+)?%)"},
    "indemnity_cap": {"doc": ("spa",), "re": r"(?:cap|aggregate liability|maximum liability)[^.]{0,120}?((?:US\$|\$|£|€)\s?[\d,]+(?:\.\d+)?(?:\s?(?:million|billion))?|\d+(?:\.\d+)?%)"},
    "basket": {"doc": ("spa",), "re": r"(?:basket|deductible)[^.]{0,100}?((?:US\$|\$|£|€)\s?[\d,]+(?:\.\d+)?(?:\s?(?:million|billion))?|\d+(?:\.\d+)?%)"},
    "material_adverse_effect": {"doc": ("spa", "credit"), "re": r"(material adverse (?:effect|change))"},
    "change_of_control": {"doc": ("spa", "credit"), "re": r"(change (?:of|in) control)"},
    "max_leverage": {"doc": ("credit",),
                     "re": r"(?:leverage ratio|total net leverage)[^.]{0,160}?(\d+(?:\.\d+)?)\s*(?:to|:)\s*(?:1\.00|1(?:\.0)?)"},
    "min_interest_coverage": {"doc": ("credit",),
                              "re": r"(?:interest coverage|fixed charge coverage)[^.]{0,160}?(\d+(?:\.\d+)?)\s*(?:to|:)\s*(?:1\.00|1(?:\.0)?)"},
    "margin": {"doc": ("credit",),
               "re": r"(?:applicable margin|margin)[^.]{0,120}?(\d+(?:\.\d+)?%|\d{2,3}\s*basis points)"},
    "maturity": {"doc": ("credit",), "re": r"(?:maturity date|matures?)[^.]{0,80}?((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})"},
}


@dataclass
class Finding:
    term: str
    value: str
    page: int
    quote: str
    needs_review: bool


def extract(pages: list[tuple[int, str]], doc_type: str) -> dict:
    """pages: (number, text). doc_type: nda | spa | credit. Returns findings and absent term names."""
    if doc_type not in ("nda", "spa", "credit"):
        raise ValueError("doc_type must be nda, spa or credit")
    found: list[Finding] = []
    absent = []
    for term, spec in TERMS.items():
        if doc_type not in spec["doc"]:
            continue
        rx = re.compile(spec["re"], re.IGNORECASE if term not in ("governing_law",) else 0)
        hits = 0
        for num, text in pages:
            flat = re.sub(r"\s+", " ", text)
            for sent in _SENT.split(flat):
                m = rx.search(sent)
                if m:
                    hits += 1
                    found.append(Finding(term, m.group(1).strip(), num, sent.strip(),
                                         bool(_NEG.search(sent))))
        if not hits:
            absent.append(term)
    return {"doc_type": doc_type, "findings": [f.__dict__ for f in found], "absent": absent}
