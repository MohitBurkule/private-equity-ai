"""Turn a stored vendor/platform CSV export into cited fact proposals.

Works on documents made by `ingest_csv` (lines `row N: Header=value | Header=value`), so every proposal
quotes the exact `Header=value` text on its page and goes through the normal fact gate. Presets map
common export headers to metrics. They are NOT verified against real exports (none were available when
this was written, and PitchBook/Seedrs/Crowdcube layouts change): a header that matches nothing yields no
proposal, and any value whose currency or scale cannot be read is rejected with a reason, never guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

PRESETS: dict[str, dict] = {
    "pitchbook": {
        "entity": ["companies", "company name", "company", "company id name"],
        "period": ["last financing date", "deal date", "financing date"],
        "currency": ["currency", "deal currency"],
        "metrics": {
            "post_money_valuation": ["post valuation", "post-money valuation", "post money valuation", "post money"],
            "last_financing_size": ["last financing size", "deal size", "financing size"],
            "total_raised": ["total raised", "total capital raised"],
        },
    },
    "crowdcube": {
        "entity": ["company", "company name", "business", "campaign"],
        "period": ["date", "investment date", "trade date"],
        "currency": ["currency"],
        "metrics": {
            "investment_amount": ["amount invested", "investment amount", "investment", "amount"],
            "shares_held": ["shares", "number of shares", "shares held"],
            "price_per_share": ["price per share", "share price", "price"],
            "valuation": ["valuation", "pre-money valuation", "pre money valuation"],
        },
    },
}
PRESETS["seedrs"] = PRESETS["republic"] = PRESETS["crowdcube"]

_CELL = re.compile(r"\s\|\s")
_ROW = re.compile(r"^row (\d+): (.*)$")
_HDR_UNIT = re.compile(r"\(([^)]*)\)\s*$")
_SCALES = {"k": Decimal(10) ** 3, "000": Decimal(10) ** 3, "m": Decimal(10) ** 6, "mm": Decimal(10) ** 6,
           "mn": Decimal(10) ** 6, "million": Decimal(10) ** 6, "bn": Decimal(10) ** 9, "b": Decimal(10) ** 9}
_SYM = {"£": "GBP", "$": "USD", "€": "EUR"}
_COUNT_METRICS = {"shares_held"}


@dataclass
class Proposal:
    entity: str
    metric: str
    period: str
    value: Decimal
    unit: str
    scale: Decimal
    page: int
    quote: str
    row: int


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", _HDR_UNIT.sub("", h).strip().lower())


def _header_unit(h: str) -> tuple[str | None, Decimal]:
    m = _HDR_UNIT.search(h)
    cur, scale = None, Decimal(1)
    if m:
        for tok in re.split(r"[\s,/]+", m.group(1).strip()):
            if re.fullmatch(r"[A-Za-z]{3}", tok) and tok.lower() not in _SCALES:
                cur = tok.upper()
            elif tok.lower() in _SCALES:
                scale = _SCALES[tok.lower()]
    return cur, scale


def propose(pages: list[tuple[int, str]], preset: str, default_currency: str | None = None):
    """Return (proposals, rejected). `rejected` are dicts with page, row, field and reason."""
    if preset not in PRESETS:
        raise ValueError(f"preset must be one of {sorted(PRESETS)}")
    cfg = PRESETS[preset]
    out: list[Proposal] = []
    bad: list[dict] = []
    for page, text in pages:
        for line in text.splitlines():
            m = _ROW.match(line)
            if not m:
                continue
            row = int(m.group(1))
            cells: dict[str, tuple[str, str, str]] = {}  # normalised header -> (raw header, value, cell text)
            for cell in _CELL.split(m.group(2)):
                if "=" in cell:
                    h, v = cell.split("=", 1)
                    cells[_norm(h)] = (h.strip(), v.strip(), cell.strip())
            def pick(names, cells=cells):
                return next((cells[n] for n in names if n in cells), None)
            ent, per = pick(cfg["entity"]), pick(cfg["period"])
            cur_col = pick(cfg["currency"])
            if not ent:
                continue
            for metric, names in cfg["metrics"].items():
                hit = pick(names)
                if not hit:
                    continue
                raw_h, val, cell = hit

                def reject(why, page=page, row=row, metric=metric):
                    bad.append({"page": page, "row": row, "field": metric, "reason": why})
                if not per:
                    reject("no date column to use as the period")
                    continue
                num = val
                cur, scale = _header_unit(raw_h)
                if num[:1] in _SYM:
                    cur, num = cur or _SYM[num[0]], num[1:]
                if metric in _COUNT_METRICS:
                    cur = "shares"
                cur = cur or (cur_col[1].upper() if cur_col else None) or (default_currency or "").upper() or None
                if not cur:
                    reject("currency not stated in the header, a symbol, a currency column or the request")
                    continue
                try:
                    d = Decimal(num.replace(",", ""))
                except InvalidOperation:
                    reject(f"not a number: {val!r}")
                    continue
                if not d.is_finite() or d < 0:
                    reject(f"unusable number: {val!r}")
                    continue
                out.append(Proposal(ent[1], metric, per[1], d * scale, cur, scale, page, cell, row))
    return out, bad
