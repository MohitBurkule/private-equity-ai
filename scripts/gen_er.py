"""Regenerate the ER diagram block in docs/DIAGRAMS.md from the SQLAlchemy models.

  cd apps/api && python ../../scripts/gen_er.py
"""
import re
from pathlib import Path

import app.models  # noqa: F401 - registers tables
from app.db import Base

tables = sorted(Base.metadata.tables.values(), key=lambda t: t.name)
out = ["erDiagram"]
for t in tables:
    out.append(f"  {t.name} {{")
    for c in t.columns:
        ty = str(c.type).split("(")[0].replace(" ", "_") or "x"
        tag = " PK" if c.primary_key else (" FK" if c.foreign_keys else "")
        out.append(f"    {ty} {c.name}{tag}")
    out.append("  }")
for t in tables:
    for fk in t.foreign_keys:
        out.append(f'  {fk.column.table.name} ||--o{{ {t.name} : "{fk.parent.name}"')
block = "```mermaid\n" + "\n".join(out) + "\n```"
p = Path(__file__).parents[1] / "docs" / "DIAGRAMS.md"
s = p.read_text()
p.write_text(re.sub(r"<!-- er:start -->.*<!-- er:end -->", lambda _: "<!-- er:start -->\n" + block + "\n<!-- er:end -->", s, flags=re.S))
