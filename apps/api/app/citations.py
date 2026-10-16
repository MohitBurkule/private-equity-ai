"""Span-level citations and deterministic numeric verification.

A Span points at exact text in a document page. Numbers in a claim are checked
by code against the span text; an LLM never judges numeric correctness.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_NUM = re.compile(r"\(?-?\$?\s*\d[\d,]*(?:\.\d+)?\)?")


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
                  allow_sign_flip: bool = True) -> bool:
    """True if claimed (already in output units) equals some number in the span
    after applying the table scale (e.g. 1000 for $ thousands -> multiply).

    allow_sign_flip: outflows are shown in parentheses but asked about as positives.
    """
    for n in numbers_in(span_text):
        v = n.value * scale
        if v == claimed or (allow_sign_flip and abs(v) == abs(claimed)):
            return True
    return False
