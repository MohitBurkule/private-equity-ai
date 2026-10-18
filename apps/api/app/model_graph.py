"""Assumptions and outputs of an Excel model, from its formula graph.

An assumption is a typed number that at least one formula reads. An output is a formula that no other formula reads:
the figure the model exists to show. Both lists name their cells, so a reviewer can see what the model is driven by and
what it reports. Ranges are read by their end cells only; a formula the parser cannot read is left out of the graph, not
guessed at.
"""
from __future__ import annotations

import io
import re

from openpyxl import load_workbook

# Optional sheet name (quoted or bare), then a cell; $ anchors are allowed.
_REF = re.compile(r"(?:'([^']+)'|([A-Za-z_][A-Za-z0-9_.]*))?!?\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?")


def _cells(formula: str, here: str) -> set[tuple[str, str]]:
    """(sheet, coordinate) of every cell a formula reads. Ranges contribute their two end cells."""
    out: set[tuple[str, str]] = set()
    for m in _REF.finditer(formula):
        sheet = m.group(1) or m.group(2) or here
        out.add((sheet, f"{m.group(3)}{m.group(4)}"))
        if m.group(5):
            out.add((sheet, f"{m.group(5)}{m.group(6)}"))
    return out


def graph(data: bytes) -> dict:
    wb = load_workbook(io.BytesIO(data), data_only=False)
    formulas: dict[tuple[str, str], str] = {}
    numbers: dict[tuple[str, str], float] = {}
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    formulas[(ws.title, c.coordinate)] = c.value
                elif isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
                    numbers[(ws.title, c.coordinate)] = c.value
    read: set[tuple[str, str]] = set()
    for key, f in formulas.items():
        read |= _cells(f, key[0])
    assumptions = [{"cell": f"{s}!{a}", "value": v} for (s, a), v in sorted(numbers.items()) if (s, a) in read]
    outputs = [{"cell": f"{s}!{a}", "formula": f} for (s, a), f in sorted(formulas.items()) if (s, a) not in read]
    return {"assumptions": assumptions, "outputs": outputs, "formula_cells": len(formulas)}
