"""Funding history for a target from a Crunchbase legacy funding_rounds export.

Rounds match the target by company name (case-insensitive, exact). Each round keeps the data row it came from,
so the history cites the export and row. Rounds with no match are not returned, and nothing is guessed from
similar names."""
from __future__ import annotations

from app.crunchbase import FundingRound


def funding_for_target(rows: list[tuple[int, FundingRound]], target_name: str, source: str) -> list[dict]:
    want = target_name.strip().lower()
    out = []
    for n, r in rows:
        if (r.company or "").strip().lower() != want:
            continue
        out.append({
            "round_type": r.round_type,
            "announced": r.announced.isoformat() if r.announced else None,
            "raised_usd": str(r.raised_usd) if r.raised_usd is not None else None,
            "post_money_usd": str(r.post_money_usd) if r.post_money_usd is not None else None,
            "investors": r.investors,
            "citation": {"source": source, "row": n},
        })
    return sorted(out, key=lambda x: x["announced"] or "")
