"""Excel ingest: one 'page' per sheet, cell-addressed lines so citations point at cells.

Keeps formulas AND cached values, flags hidden sheets. Macros are never executed
(openpyxl reads only). Line format:  "Sheet1!B7: 1,234 [=SUM(B2:B6)]"
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook


@dataclass(frozen=True)
class Sheet:
    doc_id: str
    number: int  # 1-based sheet index
    name: str
    hidden: bool
    text: str


def extract_sheets(path: Path) -> list[Sheet]:
    doc_id = hashlib.sha256(path.read_bytes()).hexdigest()
    values = load_workbook(path, data_only=True, read_only=False)
    formulas = load_workbook(path, data_only=False, read_only=False)
    out = []
    for i, ws in enumerate(values.worksheets, 1):
        fws = formulas[ws.title]
        lines = []
        for row in ws.iter_rows():
            # Row label: first text cell in the row. Carried on each numeric line so the
            # quote's page line names the line item (the gate's label check reads it).
            label = next((str(c.value) for c in row if isinstance(c.value, str) and c.value.strip()), None)
            for c in row:
                f = fws[c.coordinate].value
                is_formula = isinstance(f, str) and f.startswith("=")
                if c.value is None and not is_formula:
                    continue
                suffix = f" [{f}]" if is_formula else ""
                if c.value is None:  # never silently drop: workbook was saved without calculation
                    v = "(no cached value)"
                else:
                    v = f"{c.value:,}" if isinstance(c.value, (int, float)) else str(c.value)
                row_note = f" | row: {label}" if label and label != str(c.value) else ""
                lines.append(f"{ws.title}!{c.coordinate}: {v}{suffix}{row_note}")
        hidden = ws.sheet_state != "visible"
        head = f"[hidden sheet: {ws.sheet_state}]\n" if hidden else ""
        out.append(Sheet(doc_id, i, ws.title, hidden, head + "\n".join(lines)))
    return out
