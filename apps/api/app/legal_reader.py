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


def read(pages: list[tuple[int, str]], doc_type: str, absent: list[str], llm) -> dict:
    findings, dropped = [], []
    page_text = {num: _flat(text) for num, text in pages}
    for term in absent:
        spec = legal.TERMS.get(term)
        if spec is None or doc_type not in spec["doc"]:
            continue
        if term not in KEYWORDS:
            dropped.append({"term": term, "reason": "no keywords defined for this term, so the model was not asked"})
            continue
        cands = candidates(term, pages)
        if not cands:
            dropped.append({"term": term, "reason": "no sentence with the term's keywords"})
            continue
        listing = "\n".join(f"[p{num}] {sent}" for num, sent in cands)
        try:
            reply = json.loads(llm.complete(SYSTEM, f"Term: {term.replace('_', ' ')}\n\nSentences:\n{listing}"))
        except (ValueError, AttributeError, TypeError):
            dropped.append({"term": term, "reason": "model reply was not JSON"})
            continue
        quote, page = reply.get("quote"), reply.get("page")
        if not quote:
            dropped.append({"term": term, "reason": "model found no sentence"})
            continue
        quote = _flat(str(quote)).strip()
        if page not in page_text or quote not in page_text[page]:
            dropped.append({"term": term, "reason": "quote is not on the cited page"})
            continue
        m = re.search(spec["re"], quote, re.IGNORECASE if term != "governing_law" else 0)
        if not m:
            dropped.append({"term": term, "reason": "quote does not state the term"})
            continue
        findings.append({"term": term, "value": m.group(1) if m.groups() else None, "page": page, "quote": quote,
                         "source": "local model second reader"})
    return {"findings": findings, "dropped": dropped}
