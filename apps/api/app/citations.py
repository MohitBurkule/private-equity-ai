"""Span-level citations and deterministic numeric verification.

A Span points at exact text in a document page. Numbers in a claim are checked
by code against the span text; an LLM never judges numeric correctness.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# A parenthesised figure may have spaces inside, as iXBRL tables print "( 747 )".
_NUM = re.compile(r"\(\s*\$?\s*\d[\d,]*(?:\.\d+)?\s*\)|-?\$?\s*\d[\d,]*(?:\.\d+)?")
_LOSS_CUE = re.compile(r"\(loss\)|\bloss\b", re.IGNORECASE)


@dataclass(frozen=True)
class Span:
    doc_id: str
    page: int  # 1-based PDF page
    text: str  # exact quoted text
    page_label: str | None = None  # printed page number
    bbox: tuple[float, float, float, float] | None = None
    table_id: str | None = None
    row_label: str | None = None


@dataclass(frozen=True)
class ParsedNumber:
    raw: str
    value: Decimal  # signed: parentheses mean negative


def parse_number(raw: str) -> ParsedNumber | None:
    s = raw.strip()
    neg = (s.startswith("(") and s.endswith(")")) or "-" in s
    digits = re.sub(r"[^\d.]", "", s)
    if not digits or digits == ".":
        return None
    try:
        v = Decimal(digits)
    except InvalidOperation:
        return None
    return ParsedNumber(raw=raw, value=-v if neg else v)


def numbers_in(text: str) -> list[ParsedNumber]:
    out = []
    for m in _NUM.finditer(text):
        p = parse_number(m.group())
        if p is not None:
            out.append(p)
    return out


def quote_in_page(quote: str, page_text: str) -> bool:
    """Whitespace-insensitive, case-insensitive substring check."""
    norm = lambda t: re.sub(r"\s+", " ", t).strip().lower()
    q = norm(quote)
    return bool(q) and q in norm(page_text)


def verify_number(claimed: Decimal, span_text: str, scale: Decimal = Decimal(1),
                  outflow: bool = False) -> bool:
    """True if claimed (already in output units) equals some number in the span after applying
    the table scale (e.g. 1000 for $ thousands -> multiply).

    The sign must match the printed sign, because a sign error turns a loss into a profit. Two
    cases may differ: an outflow label (capex, repayments, dividends paid) is asked as a positive
    magnitude while the table shows it in parentheses; and a loss is asked as negative while the
    quote names it a loss without parentheses.
    """
    for n in numbers_in(span_text):
        v = n.value * scale
        if v == claimed:
            return True
        if abs(v) != abs(claimed):
            continue
        if outflow:
            return True
        if v > 0 and claimed < 0 and _LOSS_CUE.search(span_text):
            return True
    return False


def locator_label(page: int, section: str | None = None, heading: str | None = None) -> str:
    """How a citation is shown to a reader. PDFs have pages. HTML filings have none, so they are labelled by
    section and heading; page 0 is a storage sentinel and must never reach a reader."""
    if page:
        return f"p.{page}"
    if section:
        return f"§{section}" + (f" {heading}" if heading else "")
    return "HTML filing"
