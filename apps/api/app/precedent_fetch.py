"""Precedent deals from SEC filings: find merger 8-Ks with dealscan, read each filing, extract terms with precedents.

Each deal keeps the filing URL, so every stated EV and multiple cites the filing it came from. A filing that
fails to download or has no stated terms is listed under `skipped` with the reason, never guessed. Needs
SEC_USER_AGENT (SEC rejects anonymous requests). Tests inject a fake fetch, so no network runs in CI.
"""

from __future__ import annotations

import html
import re

from app import dealscan, precedents
from app.secfeed import default_fetch

Fetch = dealscan.Fetch
_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</(?:p|div|tr|li|h\d)>|<br\s*/?>", re.IGNORECASE)
_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


def filing_text(raw: bytes) -> str:
    """HTML filing to plain text, with block tags kept as sentence breaks so quotes stay readable."""
    s = _SCRIPT.sub(" ", raw.decode("utf-8", errors="replace"))
    s = _BLOCK.sub(". ", s)
    return html.unescape(_TAG.sub(" ", s))


def build(
    since: str, until: str, fetch: Fetch = default_fetch, limit: int = 25
) -> dict:
    leads = dealscan.scan(since, until, fetch=fetch)[:limit]
    deals, skipped = [], []
    for lead in leads:
        name = f"{lead.company} ({lead.filed})"
        try:
            text = filing_text(fetch(lead.url))
        except Exception as e:  # noqa: BLE001  one bad filing must not stop the rest
            skipped.append(
                {"name": name, "url": lead.url, "reason": f"download failed: {e}"}
            )
            continue
        terms = precedents.extract([(1, text)])
        for m in terms["multiples"]:
            m["source_url"] = lead.url
        if terms["ev_musd"]:
            terms["ev_musd"]["source_url"] = lead.url
        if not terms["multiples"] and not terms["ev_musd"]:
            skipped.append(
                {"name": name, "url": lead.url, "reason": "no stated EV or multiple"}
            )
            continue
        deals.append({"name": name, "document_id": lead.url, "terms": terms})
    return {"deals": deals, "skipped": skipped, "stats": precedents.summarise(deals)}
