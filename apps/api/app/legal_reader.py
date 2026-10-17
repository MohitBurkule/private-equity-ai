"""Second reader for legal terms the rules-based extractor did not find, using the local model.

The model is asked, per absent term, for one sentence from the document that states the term. Its answer is kept
only if the quote is on the cited page (whitespace-normalised) and the term's own pattern matches it. Anything
without a quote that passes both checks is dropped and listed under `dropped` with the reason, never shown as a finding.
"""
from __future__ import annotations

import json
import re

from app import legal

# Words that make a sentence worth showing the model for each term. A term with no keyword hit is not asked about.
KEYWORDS = {
    "governing_law": ("governing law", "governed by"),
    "material_adverse_effect": ("material adverse",),
    "change_of_control": ("change of control", "change in control"),
    "max_leverage": ("leverage ratio", "leverage"),
    "min_interest_coverage": ("interest coverage",),
    "margin": ("margin", "applicable rate"),
    "maturity": ("maturity", "matures"),
    "non_solicit_months": ("solicit",),
    "non_compete_months": ("non-compet", "noncompet", "non compet"),
    "purchase_price": ("purchase price",),
    "escrow": ("escrow",),
    "indemnity_cap": ("cap", "indemnif"),
    "basket": ("basket", "deductible"),
    "termination_fee": ("termination fee",),
}
MAX_SENTENCES = 12
SYSTEM = ("You read one legal document excerpt. Copy one sentence, exactly as written, that states the term named. "
          'Reply as JSON only: {"quote": "<exact sentence>", "page": <number>} or {"quote": null}.')


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def candidates(term: str, pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    keys = [k.lower() for k in KEYWORDS.get(term, ())]
    out = []
    for num, text in pages:
        for sent in legal._SENT.split(_flat(text)):
            if any(k in sent.lower() for k in keys):
                out.append((num, sent.strip()))
    return out[:MAX_SENTENCES]


def _ask(term: str, spec: dict, pages: list[tuple[int, str]], llm) -> tuple[dict | None, str | None]:
    """The model's quote for one term, or None with the reason. Gate: the quote is on the cited page and the term's
    pattern matches it. Nothing else gets through."""
    cands = candidates(term, pages)
    if not cands:
        return None, "no sentence with the term's keywords"
    listing = "\n".join(f"[p{num}] {sent}" for num, sent in cands)
    try:
        reply = json.loads(llm.complete(SYSTEM, f"Term: {term.replace('_', ' ')}\n\nSentences:\n{listing}"))
    except (ValueError, AttributeError, TypeError):
        return None, "model reply was not JSON"
    quote, page = reply.get("quote"), reply.get("page")
    if not quote:
        return None, "model found no sentence"
    quote = _flat(str(quote)).strip()
    if page not in {num for num, _ in pages} or quote not in _flat(dict(pages)[page]):
        return None, "quote is not on the cited page"
    m = re.search(spec["re"], quote, re.IGNORECASE)
    if not m:
        return None, "quote does not state the term"
    return {"term": term, "value": m.group(1) if m.groups() else None, "page": page, "quote": quote,
            "source": "local model second reader"}, None


def _same(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    a, b = a.lower().strip(), b.lower().strip()
    return a == b or a in b or b in a


def read(pages: list[tuple[int, str]], doc_type: str, absent: list[str], llm, found: list[dict] = ()) -> dict:
    """Absent terms: the model's cited finding, or a dropped reason. Found terms (the rules' own findings): the model
    is asked too, and a disagreement goes to `review` for a person. No automatic pick between the two."""
    findings, dropped, review = [], [], []
    for term in absent:
        spec = legal.TERMS.get(term)
        if spec is None or doc_type not in spec["doc"]:
            continue
        if term not in KEYWORDS:
            dropped.append({"term": term, "reason": "no keywords defined for this term, so the model was not asked"})
            continue
        got, why = _ask(term, spec, pages, llm)
        if got:
            findings.append(got)
        else:
            dropped.append({"term": term, "reason": why})
    for rule in found:
        term = rule["term"]
        spec = legal.TERMS.get(term)
        if spec is None or doc_type not in spec["doc"] or term not in KEYWORDS:
            continue
        got, why = _ask(term, spec, pages, llm)
        if got is None:
            review.append({"term": term, "rule_value": rule.get("value"), "status": "model_did_not_confirm",
                           "reason": why})
        elif _same(rule.get("value"), got["value"]):
            review.append({"term": term, "rule_value": rule.get("value"), "model_value": got["value"],
                           "status": "agree", "quote": got["quote"], "page": got["page"]})
        else:
            review.append({"term": term, "rule_value": rule.get("value"), "model_value": got["value"],
                           "status": "conflict", "quote": got["quote"], "page": got["page"]})
    return {"findings": findings, "dropped": dropped, "review": review}
