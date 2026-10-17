"""Precedent deals from SEC filings: find merger 8-Ks with dealscan, read each filing, extract terms with precedents.

Each deal keeps the filing URL, so every stated EV and multiple cites the filing it came from. A filing that
fails to download or has no stated terms is listed under `skipped` with the reason, never guessed. Needs
SEC_USER_AGENT (SEC rejects anonymous requests). Tests inject a fake fetch, so no network runs in CI.
"""

from __future__ import annotations

import html
import json
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


def exhibit_urls(lead_url: str, fetch: Fetch) -> list[str]:
    """The filing itself plus its EX-99 press-release exhibits, which usually state EV and multiples."""
    base = lead_url.rsplit("/", 1)[0]
    try:
        items = json.loads(fetch(f"{base}/index.json"))["directory"]["item"]
    except (OSError, ValueError, KeyError):
        return [lead_url]
    names = [i["name"] for i in items if re.match(r"(?i)ex-?99", i["name"])]
    urls = [f"{base}/{n}" for n in names if n.lower().endswith((".htm", ".html"))]
    return [lead_url] + [u for u in urls if u != lead_url]


def build(
    since: str, until: str, fetch: Fetch = default_fetch, limit: int = 25
) -> dict:
    leads = dealscan.scan(since, until, fetch=fetch)[:limit]
    deals, skipped = [], []
    for lead in leads:
        name = f"{lead.company} ({lead.filed})"
        terms: dict = {"ev_musd": None, "multiples": [], "absent": []}
        failed = None
        for url in exhibit_urls(lead.url, fetch):
            try:
                text = filing_text(fetch(url))
            except Exception as e:  # noqa: BLE001  one bad document must not stop the rest
                failed = failed or f"download failed: {e}"
                continue
            part = precedents.extract([(1, text)])
            for m in part["multiples"]:
                m["source_url"] = url
                terms["multiples"].append(m)
            if part["ev_musd"] and terms["ev_musd"] is None:
                part["ev_musd"]["source_url"] = url
                terms["ev_musd"] = part["ev_musd"]
        if not terms["multiples"] and not terms["ev_musd"]:
            skipped.append(
                {
                    "name": name,
                    "url": lead.url,
                    "reason": failed or "no stated EV or multiple",
                }
            )
            continue
        deals.append({"name": name, "document_id": lead.url, "terms": terms})
    return {"deals": deals, "skipped": skipped, "stats": precedents.summarise(deals)}
