"""Save an openpyxl workbook with fixed document and zip timestamps. Same content must give the same bytes, or a
re-sync sees a changed version and ingests the workbook again."""
from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime

from openpyxl import Workbook

_FIXED = datetime(2000, 1, 1, tzinfo=UTC)


def save_stable(wb: Workbook) -> bytes:
    wb.properties.created = wb.properties.modified = _FIXED.replace(tzinfo=None)
    raw = io.BytesIO()
    wb.save(raw)
    out = io.BytesIO()
    with zipfile.ZipFile(raw) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            entry = zipfile.ZipInfo(info.filename, date_time=_FIXED.timetuple()[:6])
            entry.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(entry, src.read(info.filename))
    return out.getvalue()
