"""Fund-admin workbook → cited facts, read from the cell lines the xlsx ingest stored ("Sheet!B2: 1,234 | row: ...").

Template: sheet 'Capital Calls' has headers in row 1 including 'Date' and 'Amount (USD)'; each later row is one call,
stated as capital_call_usd for the call date. Sheet 'NAV' has 'As of' and 'NAV (USD)'; each later row is nav_usd for
its date. A sheet that does not match the template gives nothing, so an unknown layout is never guessed at.
Each fact's quote is the cell text as it appears on its page, so the citation check passes on the stored text."""
from __future__ import annotations

import re
from dataclasses import dataclass

CALLS, NAV = "Capital Calls", "NAV"
_LINE = re.compile(r"^(?P<sheet>.+?)!(?P<col>[A-Z]{1,3})(?P<row>\d+): (?P<rest>.*)$")


@dataclass(frozen=True)
class Found:
    metric: str
    period: str
    value: str  # printed number, commas removed
    page: int
    quote: str
    entity: str | None = None  # set when a row names its own company or holder; else the deal's entity is used


def _raw(rest: str) -> str:
    return rest.split(" | ", 1)[0].split(" [", 1)[0].strip()


def _cells(pages: list[tuple[int, str]]) -> dict[tuple[str, str, int], tuple[str, int, str]]:
    out = {}
    for num, text in pages:
        for line in text.splitlines():
            m = _LINE.match(line.strip())
            if m:
                key = (m["sheet"], m["col"], int(m["row"]))
                out[key] = (_raw(m["rest"]), num, f"{m['sheet']}!{m['col']}{m['row']}: {_raw(m['rest'])}")
    return out


def extract(pages: list[tuple[int, str]]) -> list[Found]:
    cells = _cells(pages)
    headers = {(s, c): raw for (s, c, r), (raw, _, _) in cells.items() if r == 1}
    rows = {}
    for (s, c, r), v in cells.items():
        if r > 1:
            rows.setdefault(s, {}).setdefault(r, {})[c] = v
    out: list[Found] = []
    for sheet, metric, amount_hdr, date_hdr in ((CALLS, "capital_call_usd", "Amount (USD)", "Date"),
                                                (NAV, "nav_usd", "NAV (USD)", "As of")):
        amount_cols = [c for (s, c), h in headers.items() if s == sheet and h == amount_hdr]
        date_cols = [c for (s, c), h in headers.items() if s == sheet and h == date_hdr]
        if not amount_cols or not date_cols:
            continue
        for r, row in sorted(rows.get(sheet, {}).items()):
            amount = row.get(amount_cols[0])
            date = row.get(date_cols[0])
            if amount is None or date is None:
                continue
            raw, page, quote = amount
            digits = raw.replace(",", "")
            if not re.fullmatch(r"\d+(\.\d+)?", digits):
                continue  # not a plain number: leave it for a person, do not guess
            out.append(Found(metric, date[0], digits, page, quote))
    return out


# A capital-call notice (PDF, ILPA-style labels). Each label is read from its own line of the page text, and the
# fact cites that line. The period is the due date printed on the same page; without both, nothing is stored.
_NOTICE_AMOUNT = re.compile(r"Call amount:\s*USD\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)")
_NOTICE_DUE = re.compile(r"Due date:\s*(\d{4}-\d{2}-\d{2})")


def extract_notice(pages: list[tuple[int, str]]) -> list[Found]:
    out: list[Found] = []
    for num, text in pages:
        flat = re.sub(r"[ \t]+", " ", text)
        amount = _NOTICE_AMOUNT.search(flat)
        due = _NOTICE_DUE.search(flat)
        if amount is None or due is None:
            continue
        out.append(Found("capital_call_usd", due.group(1), amount.group(1).replace(",", ""), num, amount.group(0)))
    return out
