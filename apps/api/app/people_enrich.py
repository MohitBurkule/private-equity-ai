"""Free people enrichment, as an alternative to LinkedIn: named people for a company from public sources.

- Companies House: active officers and active individual persons with significant control (needs
  COMPANIES_HOUSE_API_KEY, read by chfeed).
- SEC: executive officer names from the "Executive Officers" section of a 10-K or DEF 14A (SEC_USER_AGENT).

Every person carries the page or filing they came from and the sentence they were read from. A name with no
source is never returned, and nothing beyond the source's own words is inferred. Fetches are injectable, and
the SEC URL must be on sec.gov, so this cannot be pointed at an arbitrary host."""
from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import urlparse

from app import chfeed
from app.secfeed import default_fetch as sec_default_fetch

CH_OFFICERS = "https://find-and-update.company-information.service.gov.uk/company/{n}/officers"
CH_PSC = "https://find-and-update.company-information.service.gov.uk/company/{n}/persons-with-significant-control"
SEC_HOSTS = ("www.sec.gov", "sec.gov")
MAX_SEC_PEOPLE = 30
_HEADING = re.compile(r"executive\s+officers", re.IGNORECASE)
# "Jane A. Smith, 52, Chief Financial Officer and Treasurer." (name, age, position)
_NEXT_ITEM = re.compile(r"\bItem\s+\d", re.IGNORECASE)
_EXEC = re.compile(r"([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,3}),\s*(\d{2})\s*[,.]?\s*([^.]{3,120})\.")


def companies_house_people(number: str, fetch: chfeed.Fetch = chfeed.default_fetch) -> list[dict]:
    n = chfeed.normalise_number(number)
    out = []
    for o in chfeed.officers(n, fetch):
        if o.active and o.name:
            out.append({"name": o.name, "role": o.role or "officer", "source": "Companies House officers",
                        "url": CH_OFFICERS.format(n=n),
                        "quote": f"{o.name}, {o.role or 'officer'}, appointed {o.appointed_on or 'unknown'}"})
    for p in chfeed.pscs(n, fetch):
        if p.active and p.kind == "individual" and p.name:
            natures = "; ".join(p.natures_of_control) or "control"
            out.append({"name": p.name, "role": "person with significant control",
                        "source": "Companies House PSC", "url": CH_PSC.format(n=n),
                        "quote": f"{p.name}, {natures}"})
    return out


def sec_executives(filing_text: str, url: str, form: str) -> list[dict]:
    """Names from every "Executive Officers" section of a filing's plain text. Each name keeps its sentence."""
    if urlparse(url).scheme != "https" or urlparse(url).hostname not in SEC_HOSTS:
        raise ValueError("SEC filings must be https on sec.gov")
    out: list[dict] = []
    seen: set[str] = set()
    for h in _HEADING.finditer(filing_text):
        nxt = _NEXT_ITEM.search(filing_text, h.end())  # the section ends at the next Item heading
        end = min(nxt.start() if nxt else len(filing_text), h.end() + 3000)
        for m in _EXEC.finditer(filing_text, h.end(), end):
            name = m.group(1).strip()
            if name in seen:
                continue
            seen.add(name)
            out.append({"name": name, "role": m.group(3).strip(), "source": form, "url": url,
                        "quote": m.group(0).strip()})
            if len(out) >= MAX_SEC_PEOPLE:
                return out
    return out


def sec_people(url: str, form: str, fetch: Callable[[str], bytes] = sec_default_fetch) -> list[dict]:
    from app.precedent_fetch import filing_text
    if urlparse(url).scheme != "https" or urlparse(url).hostname not in SEC_HOSTS:
        raise ValueError("SEC filings must be https on sec.gov")
    return sec_executives(filing_text(fetch(url)), url, form)
