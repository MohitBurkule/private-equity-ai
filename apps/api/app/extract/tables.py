"""Deterministic statement-row extraction from page text.

Binds unit/scale per page (from table header phrases), keeps the raw string and
sign, and never guesses: rows with no numbers are not facts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from app.citations import parse_number

_SCALE = [
    (re.compile(r"in\s+billions", re.IGNORECASE), Decimal(10) ** 9),
    (re.compile(r"in\s+millions|\$\s*millions|millions\s+of", re.IGNORECASE), Decimal(10) ** 6),
    (re.compile(r"in\s+thousands|\$\s*thousands|thousands\s+of", re.IGNORECASE), Decimal(10) ** 3),
]
_ROW = re.compile(
    r"^(?P<label>[A-Za-z][^\d$]*?[A-Za-z)\]:])\s*[\.\s]*"
    r"(?P<nums>(?:\(?\$?\s*-?\d[\d,]*(?:\.\d+)?\)?\s*%?\s*){1,6})$"
)
_NUM = re.compile(r"\(?\$?\s*-?\d[\d,]*(?:\.\d+)?\)?")


@dataclass(frozen=True)
class Row:
    label: str
    raw_values: tuple[str, ...]  # left-to-right, as printed
    values: tuple[Decimal, ...]  # signed, unscaled
    scale: Decimal  # multiply values by this to get units
    page: int
    line: str


def detect_scale(text: str) -> Decimal:
    for pat, scale in _SCALE:
        if pat.search(text):
            return scale
    return Decimal(1)


def extract_rows(page_text: str, page: int) -> list[Row]:
    scale = detect_scale(page_text)
    rows: list[Row] = []
    for line in page_text.splitlines():
        line = line.strip()
        m = _ROW.match(line)
        if not m:
            continue
        raws = tuple(x.strip() for x in _NUM.findall(m.group("nums")))
        vals = tuple(p.value for r in raws if (p := parse_number(r)) is not None)
        if not vals or len(vals) != len(raws):
            continue
        rows.append(Row(m.group("label").strip(), raws, vals, scale, page, line))
    return rows
