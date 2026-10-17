"""LBO workbook intake: named ranges become LBO inputs, and each input value is checked against verified facts.

Why ties: a sponsor's model often carries a typed-in EBITDA that no cited document prints. The returns it produces
look sourced but are not. An input with no matching verified fact is flagged, never corrected, because the model
may be right and the source not yet loaded.
"""
from __future__ import annotations

import io
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.acl import fact_visible
from app.lbo import OPTIONAL, REQUIRED
from app.models import Fact

LBO_NAMES = frozenset(REQUIRED) | frozenset(OPTIONAL)


def named_inputs(data: bytes) -> dict[str, dict]:
    """Defined names that point at one cell. Cells with a formula and no cached value are reported, not read."""
    wb = load_workbook(io.BytesIO(data), data_only=True)
    out: dict[str, dict] = {}
    for name, dn in wb.defined_names.items():
        for sheet, coord in dn.destinations:
            cell = wb[sheet][coord.replace("$", "")]
            try:
                value = Decimal(str(cell.value))
            except (InvalidOperation, TypeError):
                out[name] = {"cell": f"{sheet}!{cell.coordinate}", "value": None, "reason": "not a number"}
                continue
            out[name] = {"cell": f"{sheet}!{cell.coordinate}", "value": str(value), "reason": None}
    return out


def tie(db: Session, tenant: str, scope: set[str] | None, inputs: dict[str, dict]) -> dict[str, dict]:
    """Each named input gets the verified facts whose value equals its cell value. No match is `untied`."""
    verified = db.query(Fact).filter_by(tenant_id=tenant, status="verified").all()
    visible = [f for f in verified if fact_visible(f, scope)]
    out: dict[str, dict] = {}
    for name, inp in inputs.items():
        if inp["value"] is None:
            out[name] = {**inp, "tie": "no_value", "fact_ids": []}
            continue
        value = Decimal(inp["value"])
        ids = [f.id for f in visible if f.value == value]
        out[name] = {**inp, "tie": "tied" if ids else "untied", "fact_ids": ids,
                     "is_lbo_input": name in LBO_NAMES}
    return out
