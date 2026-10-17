"""Strip personal identifiers from text before it leaves for an external model.

Financial figures are never touched: a redaction that changed a number would break the
quote check that every answer must pass. Only identifiers that name a person or an account are
replaced, each by a typed token so the model still sees that something was there.
"""
from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("NI_NUMBER", re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}\b")),
    ("SORT_CODE", re.compile(r"\b\d{2}-\d{2}-\d{2}\b")),
    ("PHONE", re.compile(r"(?<![\d.,])(?:\+44\s?\(?0?\)?|0)\d{2,4}[\s-]?\d{3,4}[\s-]?\d{3,4}(?![\d])")),
    ("CARD", re.compile(r"(?<![\d.,])(?:\d[ -]?){12,18}\d(?![\d])")),
]


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _card(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return "[CARD]" if 13 <= len(digits) <= 19 and _luhn(digits) else match.group(0)


def redact(text: str) -> str:
    for label, pattern in _PATTERNS:
        if label == "CARD":
            text = pattern.sub(_card, text)
        else:
            text = pattern.sub(f"[{label}]", text)
    return text
