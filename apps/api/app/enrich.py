"""Target enrichment from a company's own homepage: title, meta description and site name, each kept with the
URL it came from. Nothing is inferred: a missing tag stays empty. Only https homepages are fetched; IP literals
and localhost are refused so a target cannot point the fetcher at internal hosts."""
from __future__ import annotations

import ipaddress
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.models import Target


class _Head(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key in ("description", "og:description", "og:site_name") and a.get("content"):
                self.meta.setdefault(key, a["content"].strip())

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def parse_homepage(html: str) -> dict[str, str]:
    p = _Head()
    p.feed(html[:200_000])  # the head sits at the top; ignore the rest of a large page
    return {"title": _clean(p.title), "description": _clean(p.meta.get("description") or p.meta.get("og:description", "")),
            "site_name": _clean(p.meta.get("og:site_name", ""))}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()[:500]


def check_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or not host or parts.username or parts.password:
        raise ValueError("website must be an https URL without credentials")
    if host == "localhost" or host.endswith(".localhost") or "." not in host:
        raise ValueError("website host must be a public domain")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return url
    raise ValueError("website must be a domain name, not an IP address")


def enrich_website(db: Session, tenant: str, t: Target, url: str, http) -> dict[str, str]:
    url = check_url(url)
    raw = http(url, {"Accept": "text/html", "User-Agent": "pe-platform-enrich/1"})
    fields = parse_homepage(raw.decode("utf-8", "replace"))
    t.website = url
    t.web_title, t.web_description, t.web_site_name = fields["title"], fields["description"], fields["site_name"]
    t.web_checked_at = datetime.now(UTC).isoformat(timespec="seconds")
    db.commit()
    return fields
