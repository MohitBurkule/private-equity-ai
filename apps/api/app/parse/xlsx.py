"""Excel ingest: cell-addressed lines so citations point at cells, streamed into bounded text chunks.

Keeps formulas AND cached values, flags hidden sheets. Macros are never executed
(openpyxl reads only). Line format:  "Sheet1!B7: 1,234 [=SUM(B2:B6)] | row: Revenue"

A chunk is cut at a row boundary once it passes CHUNK_CHARS, so a large sheet never becomes one
text value in memory or in the database. Chunks are numbered across the workbook; each carries its sheet name.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook

from app.parse.pdf import doc_id_for

CHUNK_CHARS = int(os.environ.get("XLSX_CHUNK_CHARS", "262144"))


@dataclass(frozen=True)
class Sheet:
    doc_id: str
    number: int  # 1-based chunk index across the workbook; each chunk is stored as one page
    name: str
    hidden: bool
    text: str


def iter_sheet_chunks(path: Path, chunk_chars: int | None = None) -> Iterator[Sheet]:
    """Streams both workbooks in read-only mode. Values and formulas are read as two row streams in step, so a
    cell's formula is the one in the same position, without random access into the formula sheet."""
    limit = CHUNK_CHARS if chunk_chars is None else chunk_chars
    doc_id = doc_id_for(path)
    values = load_workbook(path, data_only=True, read_only=True)
    formulas = load_workbook(path, data_only=False, read_only=True)
    number = 0
    try:
        for ws, fws in zip(values.worksheets, formulas.worksheets):
            hidden = ws.sheet_state != "visible"
            head = f"[hidden sheet: {ws.sheet_state}]\n" if hidden else ""
            lines: list[str] = []
            size = len(head)
            sent_any = False
            for vrow, frow in zip(ws.iter_rows(min_row=1, min_col=1), fws.iter_rows(min_row=1, min_col=1)):
                label = next((str(c.value) for c in vrow if isinstance(c.value, str) and c.value.strip()), None)
                for vc, fc in zip(vrow, frow):
                    if vc.value is None and fc.value is None:
                        continue
                    f = fc.value
                    is_formula = isinstance(f, str) and f.startswith("=")
                    suffix = f" [{f}]" if is_formula else ""
                    if vc.value is None:  # never silently drop: workbook was saved without calculation
                        v = "(no cached value)"
                    else:
                        v = f"{vc.value:,}" if isinstance(vc.value, (int, float)) else str(vc.value)
                    row_note = f" | row: {label}" if label and label != str(vc.value) else ""
                    line = f"{ws.title}!{vc.coordinate}: {v}{suffix}{row_note}"
                    lines.append(line)
                    size += len(line) + 1
                if size >= limit:
                    number += 1
                    yield Sheet(doc_id, number, ws.title, hidden, head + "\n".join(lines))
                    sent_any = True
                    head, lines, size = "", [], 0
            if lines or not sent_any:  # an empty sheet still gets one page, so it stays visible in the document
                number += 1
                yield Sheet(doc_id, number, ws.title, hidden, head + "\n".join(lines))
    finally:
        values.close()
        formulas.close()


def extract_sheets(path: Path) -> list[Sheet]:
    """Whole-workbook view for callers that want every chunk at once. Ingest uses iter_sheet_chunks."""
    return list(iter_sheet_chunks(path))
