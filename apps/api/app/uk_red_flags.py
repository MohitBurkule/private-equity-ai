"""UK target red flags from Companies House pages: outstanding charges, PSC changes, officer churn.

Input is the text of the public company pages (charges, PSC, officers) with the page URL each came from.
Every flag carries that URL and the quoted line it was read from, so it can be cited like any other fact.
Late filings are not read here: the sample pages do not show the overdue state, so no flag is invented for it."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date, datetime

CHURN_RESIGNATIONS = 3  # officer resignations on the page that count as churn
PSC_WINDOW_DAYS = 365  # a PSC notified inside this window is a recent ownership change


@dataclass(frozen=True)
class Flag:
    kind: str
    title: str
    url: str
    quote: str


def _text(page: str) -> str:
    page = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.DOTALL)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page))).strip()


def _quote(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text)
    if not m:
        return None
    return text[max(0, m.start() - 40): m.end() + 80].strip()


def _date(s: str) -> date | None:
    try:
        return datetime.strptime(s.strip(), "%d %B %Y").date()
    except ValueError:
        return None


def charge_flags(page: str, url: str) -> list[Flag]:
    text = _text(page)
    m = re.search(r"(\d+) outstanding, (\d+) satisfied", text)
    if not m or int(m.group(1)) == 0:
        return []
    return [Flag("charge", f"{m.group(1)} outstanding charge(s)", url, _quote(text, r"\d+ outstanding, \d+ satisfied") or "")]


def psc_flags(page: str, url: str, today: date) -> list[Flag]:
    text = _text(page)
    out = []
    for m in re.finditer(r"Notified on (\d{1,2} \w+ \d{4})", text):
        when = _date(m.group(1))
        if when and (today - when).days <= PSC_WINDOW_DAYS:
            out.append(Flag("psc", f"PSC notified {m.group(1)}", url, text[max(0, m.start() - 20): m.end() + 40]))
    return out


def officer_flags(page: str, url: str) -> list[Flag]:
    text = _text(page)
    m = re.search(r"Officers: \d+ officers? / (\d+) resignations?", text)
    if not m or int(m.group(1)) < CHURN_RESIGNATIONS:
        return []
    return [Flag("officer_churn", f"{m.group(1)} officer resignations", url, m.group(0))]


def red_flags(pages: dict[str, str], today: date | None = None) -> list[Flag]:
    """`pages` maps kind ("charges", "psc", "officers") to (url, html). Missing kinds are skipped."""
    today = today or date.today()
    out: list[Flag] = []
    if "charges" in pages:
        out += charge_flags(pages["charges"][1], pages["charges"][0])
    if "psc" in pages:
        out += psc_flags(pages["psc"][1], pages["psc"][0], today)
    if "officers" in pages:
        out += officer_flags(pages["officers"][1], pages["officers"][0])
    return out
