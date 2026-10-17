"""News headlines from publisher RSS feeds (BBC business, PR Newswire lists). Free, no key.

Each Item keeps title, link and the feed's own date, nothing else: headlines are leads that link out, the article text
is never copied (publisher terms). XML from the network is untrusted, so DOCTYPE/ENTITY declarations are rejected.
"""
from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET  # DOCTYPE rejected before parsing
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

Fetch = Callable[[str], bytes]
FEEDS = {
    "bbc_business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "prnewswire_financial": "https://www.prnewswire.com/rss/financial-services-latest-news/private-equity-list.rss",
}


@dataclass(frozen=True)
class Item:
    feed: str
    title: str
    link: str
    published: str


def default_fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pe-ai/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(5_000_000)


def _iso(v: str) -> str:
    try:
        return parsedate_to_datetime(v).isoformat()
    except (TypeError, ValueError):
        return ""


def parse(feed: str, blob: bytes) -> list[Item]:
    head = blob[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in head:
        raise ValueError("feed rejected: DOCTYPE/ENTITY not allowed")
    root = ET.fromstring(blob)
    out = []
    for it in root.iter("item"):
        title, link = (it.findtext("title") or "").strip(), (it.findtext("link") or "").strip()
        if title and link.startswith(("http://", "https://")):
            out.append(Item(feed, title, link, _iso(it.findtext("pubDate") or "")))
    return out


def headlines(feed: str, query: str | None = None, fetch: Fetch = default_fetch) -> list[Item]:
    if feed not in FEEDS:
        raise KeyError(f"unknown feed {feed!r}; known: {sorted(FEEDS)}")
    items = parse(feed, fetch(FEEDS[feed]))
    q = (query or "").strip().lower()
    return [i for i in items if q in i.title.lower()] if q else items
