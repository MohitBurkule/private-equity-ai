"""Precedent-deal terms read from filing text (8-K, 424B, merger proxy). Pure code, no LLM.

Every number comes with the page and sentence it was read from. Enterprise value is taken only when the text
states it in dollars with a scale word; a stated multiple ("8.5x LTM revenue") is taken as written. Nothing is
derived from two numbers in the text, so a missing term stays missing and is listed under `absent`.
Summary statistics reuse comps.stats, which needs MIN_PEERS usable values before any range is shown.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app import comps

_SENT = re.compile(r"(?<=[.;])\s+(?=[A-Z(\d])")
_EV = re.compile(
    r"(?:enterprise value|transaction value|aggregate consideration)[^.]{0,80}?"
    r"\$\s?([\d,]+(?:\.\d+)?)\s*(million|billion)",
    re.IGNORECASE,
)
_MULT = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:x|times)\s+(?:the\s+)?(?:(?:LTM|last twelve months|trailing twelve months|"
    r"NTM|next twelve months|forward)\s+)?(revenue|EBITDA|adjusted EBITDA)",
    re.IGNORECASE,
)
_SCALE = {"million": Decimal(1), "billion": Decimal(1000)}


# Sentences about pro forma, banker or peer analysis state a figure that is not the deal's own price.
# They are still shown with their cite, but flagged and left out of the statistics.
_REVIEW = re.compile(
    r"pro forma|combined company|combined|implied|calculated|analysis|reviewed|premia|per share",
    re.IGNORECASE,
)


def _millions(num: str, scale: str) -> Decimal | None:
    try:
        return Decimal(num.replace(",", "")) * _SCALE[scale.lower()]
    except (InvalidOperation, KeyError):
        return None


def extract(pages: list[tuple[int, str]]) -> dict:
    """pages: (number, text). Returns the stated EV (USD millions) and multiples, each with page and quote."""
    terms: dict = {"ev_musd": None, "multiples": [], "absent": []}
    for num, text in pages:
        flat = re.sub(r"\s+", " ", text)
        for sent in _SENT.split(flat):
            s = sent.strip()
            if terms["ev_musd"] is None:
                m = _EV.search(s)
                if m:
                    val = _millions(m.group(1), m.group(2))
                    if val is not None:
                        terms["ev_musd"] = {
                            "value": str(val),
                            "page": num,
                            "quote": s,
                            "needs_review": bool(_REVIEW.search(s)),
                        }
            for m in _MULT.finditer(s):
                metric = m.group(2).lower().replace("adjusted ", "")
                terms["multiples"].append(
                    {
                        "metric": metric,
                        "value": m.group(1),
                        "page": num,
                        "quote": s,
                        "needs_review": bool(_REVIEW.search(s)),
                    }
                )
    if terms["ev_musd"] is None:
        terms["absent"].append("enterprise_value")
    if not terms["multiples"]:
        terms["absent"].append("multiple")
    return terms


def summarise(deals: list[dict]) -> dict:
    """deals: [{"name", "document_id", "terms": extract(...)}]. One stats block per metric, cites every input."""
    by_metric: dict[str, list[tuple[Decimal, dict]]] = {}
    for d in deals:
        seen: set[str] = set()
        for m in d["terms"]["multiples"]:
            val = Decimal(m["value"])
            # first positive stated multiple per metric: one deal is one data point
            if m["metric"] in seen or val <= 0 or m["needs_review"]:
                continue
            seen.add(m["metric"])
            by_metric.setdefault(m["metric"], []).append(
                (val, {"deal": d["name"], "document_id": d["document_id"], **m})
            )
    out = {}
    for metric, items in by_metric.items():
        st = comps.stats([v for v, _ in items])
        out[metric] = {
            "n": st.n,
            "q1": str(st.q1),
            "median": str(st.median),
            "q3": str(st.q3),
            "range_shown": st.n >= comps.MIN_PEERS,
            "inputs": [src for _, src in items],
        }
    return out
