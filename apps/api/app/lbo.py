"""Simple LBO returns model. Pure code; every input must carry a citation.

Inputs are the caller's: entry EBITDA, entry and exit multiples, leverage, interest rate, tax rate,
cash conversion, fees, hold period. Each input is cited (document, page, quote) or the model refuses it.
Debt is paid down from free cash flow each year; no revolver, no dividends, no management equity.
Returns are sponsor equity in at close and out at exit, so IRR is the sponsor's, not the fund's.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

REQUIRED = ("ebitda", "entry_multiple", "exit_multiple", "leverage", "interest_rate",
            "tax_rate", "cash_conversion", "fees_pct", "years")


@dataclass
class Cited:
    value: Decimal
    source: dict  # document_id, filename, page, quote


@dataclass
class Result:
    entry_ev: Decimal
    debt: Decimal
    equity: Decimal
    fees: Decimal
    schedule: list[dict] = field(default_factory=list)
    exit_ev: Decimal = Decimal(0)
    exit_net_debt: Decimal = Decimal(0)
    exit_equity: Decimal = Decimal(0)
    moic: Decimal = Decimal(0)
    irr: Decimal | None = None


def missing(inputs: dict[str, Cited]) -> list[str]:
    return [k for k in REQUIRED if k not in inputs]


def _irr(cfs: list[Decimal]) -> Decimal | None:
    """Bisection on NPV of yearly cash flows, cfs[0] at t=0. None when no sign change."""
    if not (cfs[0] < 0 < cfs[-1]):
        return None
    lo, hi = Decimal("-0.99"), Decimal(10)
    for _ in range(200):
        mid = (lo + hi) / 2
        npv = sum(cf / (1 + mid) ** t for t, cf in enumerate(cfs))
        if npv > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def run(inputs: dict[str, Cited]) -> Result:
    gap = missing(inputs)
    if gap:
        raise ValueError(f"missing inputs: {', '.join(gap)}")
    v = {k: c.value for k, c in inputs.items()}
    years = int(v["years"])
    if years < 1 or years > 10:
        raise ValueError("years must be 1 to 10")
    entry_ev = v["ebitda"] * v["entry_multiple"]
    debt = v["ebitda"] * v["leverage"]  # leverage is a multiple of EBITDA
    fees = entry_ev * v["fees_pct"] / 100
    equity = entry_ev + fees - debt
    if equity <= 0:
        raise ValueError("debt covers the whole price; equity must be positive")
    res = Result(entry_ev, debt, equity, fees)
    ebitda = v["ebitda"]
    for y in range(1, years + 1):
        interest = debt * v["interest_rate"] / 100
        cash = ebitda * v["cash_conversion"] / 100 - interest * (1 - v["tax_rate"] / 100)
        debt = max(debt - cash, Decimal(0))
        res.schedule.append({"year": y, "ebitda": str(ebitda), "interest": str(interest.quantize(Decimal("0.01"))),
                             "debt_end": str(debt.quantize(Decimal("0.01")))})
    res.exit_ev = ebitda * v["exit_multiple"]
    res.exit_net_debt = debt
    res.exit_equity = res.exit_ev - debt
    res.moic = res.exit_equity / equity
    cfs = [-equity] + [Decimal(0)] * (years - 1) + [res.exit_equity]
    res.irr = _irr(cfs)
    return res


def build_xlsx(inputs: dict[str, Cited], res: Result) -> bytes:
    """Excel export: Inputs sheet with a citation column per input, then the schedule and returns."""
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Inputs"
    ws.append(["input", "value", "document", "page", "quote"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for k in REQUIRED:
        c = inputs[k]
        ws.append([k, str(c.value), c.source.get("filename"), c.source.get("page"), c.source.get("quote")])
    ws.column_dimensions["E"].width = 80
    out = wb.create_sheet("Model")
    out.append(["line", "value"])
    for line, val in [("entry EV", res.entry_ev), ("debt at close", res.debt), ("fees", res.fees),
                      ("sponsor equity", res.equity), ("exit EV", res.exit_ev),
                      ("net debt at exit", res.exit_net_debt), ("exit equity", res.exit_equity)]:
        out.append([line, str(val)])
    out.append(["MOIC", str(res.moic)])
    out.append(["IRR", str(res.irr) if res.irr is not None else "n/a"])
    out.append([])
    out.append(["year", "ebitda", "interest", "debt_end"])
    for r in res.schedule:
        out.append([r["year"], r["ebitda"], r["interest"], r["debt_end"]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
