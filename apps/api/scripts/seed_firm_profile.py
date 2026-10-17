"""Seed the demo firm profile from the SYNTHETIC strategy document through the normal path.

Upload the text as pages, run the local open model extractor (LLM_PROVIDER=llamacpp), then accept the
saved values. Acceptance here stands in for the reviewer: each value already passed the quote and number
checks in extract_profile. Writes the accepted rows to data/seed/firm_profile.json.

Usage (from apps/api): LLM_PROVIDER=llamacpp LLAMA_MODEL_PATH=... python scripts/seed_firm_profile.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "data" / "seed" / "synthetic_firm_strategy.txt"
OUT = ROOT / "data" / "seed" / "firm_profile.json"
KEYS = ["deal_screening_criteria", "partner_signoff_threshold", "board_meeting_frequency"]
TENANT = "demo"


def main() -> int:
    if os.environ.get("LLM_PROVIDER") != "llamacpp":
        print("set LLM_PROVIDER=llamacpp and LLAMA_MODEL_PATH", file=sys.stderr)
        return 2
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/seed.db")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from sqlalchemy.orm import sessionmaker

    from app import firm_knowledge as fk
    from app.db import Base, make_engine
    from app.ingest import _store_pages
    from app.llm import get_llm
    from app.parse.office import RawPage

    engine = make_engine()
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    raw = DOC.read_bytes()
    pages = [RawPage(t.strip()) for t in raw.decode().split("\f") if t.strip()]
    doc = _store_pages(db, TENANT, raw, DOC.name, "text", pages)
    res = fk.extract_profile(db, TENANT, get_llm(), doc, KEYS)
    for r in res.saved:
        fk.review(db, TENANT, r.id, "accepted")
    db.commit()
    accepted = [fk.row_dict(r) for r in db.query(fk.FirmKnowledge).filter_by(tenant_id=TENANT,
                                                                             status="accepted").all()]
    OUT.write_text(json.dumps({"document": DOC.name, "model": os.environ.get("LLAMA_MODEL_PATH", "").rsplit("/", 1)[-1],
                               "rejected": res.rejected, "accepted": accepted}, indent=2) + "\n")
    print(f"saved {len(res.saved)}, rejected {len(res.rejected)}, accepted {len(accepted)} -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
