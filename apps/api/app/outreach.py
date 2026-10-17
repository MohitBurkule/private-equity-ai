"""Outreach drafts for acquisition targets: mail-merge from known fields only. Nothing is sent.

A sentence that needs a field the target lacks (sector, revenue) is dropped, never filled with a guess,
and a revenue sentence always names the period and links the filing it came from. The caller edits and sends.
"""
from __future__ import annotations

from decimal import Decimal

from app.models import Target


def _money(v: Decimal, cur: str | None) -> str:
    for div, suffix in ((Decimal("1e9"), "billion"), (Decimal("1e6"), "million")):
        if abs(v) >= div:
            return f"{cur or ''} {(v / div).quantize(Decimal('0.1'))} {suffix}".strip()
    return f"{cur or ''} {v:,.0f}".strip()


def draft(t: Target, sender: str, firm: str, thesis: str | None = None) -> dict:
    lines = [f"Dear {t.name} leadership team,", ""]
    intro = f"I am {sender} at {firm}."
    if t.sector:
        intro += f" We invest in businesses in {t.sector.split(' (')[0].lower()}"
        intro += f" and have been following {t.name}."
    else:
        intro += f" We have been following {t.name}."
    lines.append(intro)
    if t.revenue is not None and t.revenue_period:
        src = f" ({t.revenue_url})" if t.revenue_url else ""
        lines.append(f"Public filings show revenue of {_money(t.revenue, t.currency)} for {t.revenue_period}{src}.")
    if thesis:
        lines.append(thesis.strip())
    ask = ("If you are open to a short, confidential conversation about partnership options, "
           "I would welcome the chance to introduce ourselves.")
    lines += ["", ask, "", "Kind regards,", sender, firm]
    return {"target_id": t.id, "to_name": t.name, "subject": f"Introduction from {firm}", "body": "\n".join(lines),
            "facts_used": {"sector": t.sector, "revenue": None if t.revenue is None else str(t.revenue),
                           "revenue_url": t.revenue_url}}
