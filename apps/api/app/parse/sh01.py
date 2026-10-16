"""Read an electronic Companies House SH01 (return of allotment) from page text.

Every value comes with the page and the verbatim line it was read from, so it can be cited and
checked by the same quote-on-page rule as other facts. Nothing is inferred: a field that is not
printed is absent, and a figure that is not purely digits (OCR often turns 0 into O, 1 into l) is
reported unreadable instead of being repaired. Cross-checks (class rows against the printed total)
are returned as problems. Values from OCR pages carry `ocr: true` and need a person to confirm them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

_NUM = r"[0-9][0-9,]*(?:\.[0-9]+)?"
_DATE = r"\d{2}/\d{2}/\d{4}"
_FORM = re.compile(r"\b(SH01|SH02|SH19)\b")
_COMPANY = re.compile(r"Company\s+Number:?\s*([A-Z0-9]{8})\b")
_DATES = re.compile(rf"({_DATE})\s+({_DATE})")
_CLASS_ROW = re.compile(r"Class\s+of\s+Shares:?\s*(.+?)\s{2,}Number\s+allotted\s+(\S+)")
_NOMINAL = re.compile(r"Nominal\s+value\s+of\s+each\s+share\s+(\S+)")
_PAID = re.compile(r"Amount\s+paid:?\s+(\S+)")
_UNPAID = re.compile(r"Amount\s+unpaid:?\s+(\S+)")
_AGG = re.compile(r"Aggregate\s+nominal\s+value:?\s+(\S+)")
_TOTAL_SH = re.compile(r"Total\s+number\s+of\s+shares:?\s+(\S+)")
_TOTAL_NOM = re.compile(r"Total\s+aggregate\s+nominal\s+value:?\s+(\S+)")


@dataclass
class Value:
    value: Decimal | str | None
    page: int
    quote: str
    ocr: bool = False
    readable: bool = True


@dataclass
class Allotment:
    cls: Value
    number: Value
    nominal: Value | None = None
    paid: Value | None = None
    unpaid: Value | None = None


@dataclass
class CapitalForm:
    form: str | None = None
    company_number: Value | None = None
    date_from: Value | None = None
    date_to: Value | None = None
    allotments: list[Allotment] = field(default_factory=list)
    statement_rows: list[Allotment] = field(default_factory=list)
    total_shares: Value | None = None
    total_nominal: Value | None = None
    problems: list[str] = field(default_factory=list)


def _dec(token: str) -> Decimal | None:
    if not re.fullmatch(_NUM, token):
        return None
    try:
        return Decimal(token.replace(",", ""))
    except InvalidOperation:
        return None


def _val(token: str, page: int, line: str, ocr: bool) -> Value:
    d = _dec(token)
    return Value(d if d is not None else token, page, line.strip(), ocr, d is not None)


def parse_capital_form(pages: list[tuple[int, str, bool]]) -> CapitalForm:
    """`pages` = (page number, text, came_from_ocr)."""
    out = CapitalForm()
    for num, text, ocr in pages:
        lines = text.splitlines()
        in_statement = "Statement of Capital" in text
        if out.form is None and (m := _FORM.search(text)):
            out.form = m.group(1)
        for i, line in enumerate(lines):
            if out.company_number is None and (m := _COMPANY.search(line)):
                out.company_number = Value(m.group(1), num, line.strip(), ocr)
            if out.date_from is None and re.search(r"From\s+To", line):
                for nxt in lines[i + 1:i + 3]:
                    if m := _DATES.search(nxt):
                        out.date_from = Value(m.group(1), num, nxt.strip(), ocr)
                        out.date_to = Value(m.group(2), num, nxt.strip(), ocr)
                        break
            if m := _CLASS_ROW.search(line):
                row = Allotment(Value(m.group(1).strip(), num, line.strip(), ocr), _val(m.group(2), num, line, ocr))
                for nxt in lines[i + 1:i + 5]:
                    if "Class of Shares" in nxt:
                        break
                    for pat, attr in ((_NOMINAL, "nominal"), (_PAID, "paid"), (_UNPAID, "unpaid"), (_AGG, "nominal")):
                        if (mm := pat.search(nxt)) and getattr(row, attr) is None:
                            setattr(row, attr, _val(mm.group(1), num, nxt, ocr))
                (out.statement_rows if in_statement else out.allotments).append(row)
            if out.total_shares is None and (m := _TOTAL_SH.search(line)):
                out.total_shares = _val(m.group(1), num, line, ocr)
            if out.total_nominal is None and (m := _TOTAL_NOM.search(line)):
                out.total_nominal = _val(m.group(1), num, line, ocr)
    _check(out)
    return out


def _check(f: CapitalForm) -> None:
    if f.form is None:
        f.problems.append("form type not found")
    for name, v in (("number allotted", [a.number for a in f.allotments]), ("total shares", [f.total_shares])):
        for x in v:
            if x is not None and not x.readable:
                f.problems.append(f"{name} unreadable: {x.value!r} (page {x.page}); check the image")
    rows = [r.number for r in f.statement_rows]
    if rows and f.total_shares is not None and f.total_shares.readable and all(r.readable for r in rows):
        s = sum(r.value for r in rows)
        if s != f.total_shares.value:
            f.problems.append(f"statement-of-capital rows add to {s}, printed total is {f.total_shares.value}")
    if not f.allotments and f.form == "SH01":
        f.problems.append("no allotment row found")
