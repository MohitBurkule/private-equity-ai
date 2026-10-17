"""Full text of an inline-XBRL filing (a 10-K or 10-Q as filed), with every tagged figure.

Pages follow the filing's own page breaks, so a citation names the page a reader would turn to.
Each tagged figure keeps the table row it sits in: that row is the quote a fact cites, so the
number is always checked against text the reader can see on that page.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from app.parse.office import RawPage

_DURATION = re.compile(r"Duration_(\d{1,2})_(\d{1,2})_(\d{4})_To_(\d{1,2})_(\d{1,2})_(\d{4})")
_BREAK = re.compile(r"page-break-(after|before)\s*:\s*always", re.IGNORECASE)
_HIDDEN = re.compile(r"display\s*:\s*none", re.IGNORECASE)
# Contexts live in ix:resources (hidden). Newer filings use opaque ids like c-12, so the period is
# read from the definition, not from the id. Dimensional contexts (a segment or member) are dropped.
_CONTEXT = re.compile(r'<xbrli:context\s+id="([^"]+)"\s*>(.*?)</xbrli:context>', re.DOTALL | re.IGNORECASE)
_START = re.compile(r"<xbrli:startDate>\s*([\d-]+)\s*<", re.IGNORECASE)
_END = re.compile(r"<xbrli:endDate>\s*([\d-]+)\s*<", re.IGNORECASE)
_INSTANT = re.compile(r"<xbrli:instant>\s*([\d-]+)\s*<", re.IGNORECASE)
_DIMENSION = re.compile(r"<xbrldi:(explicitMember|typedMember)", re.IGNORECASE)


@dataclass
class Tagged:
    name: str           # e.g. us-gaap:Revenues
    context: str        # contextRef id
    scale: int          # ix scale attribute, 6 for "in millions"
    text: str           # the number as printed
    page: int           # 1-based, matches the page list
    row: str            # visible text of the table row the figure sits in
    period: str | None  # period_key(): "start/end" for a duration, "@date" for an instant
    negative: bool = False  # sign="-": the printed number is the magnitude of a negative value


def period_of(context: str) -> tuple[str, str] | None:
    """(start, end) ISO dates for a plain duration context, or None for dimensional or instant ones."""
    if "Axis" in context or "Member" in context:
        return None
    m = _DURATION.search(context)
    if not m:
        return None
    # Context ids spell the date month first: Duration_1_1_2019_To_12_31_2019 is 2019-01-01 to 2019-12-31.
    m1, d1, y1, m2, d2, y2 = (int(g) for g in m.groups())
    return f"{y1:04d}-{m1:02d}-{d1:02d}", f"{y2:04d}-{m2:02d}-{d2:02d}"


def _legacy_key(context: str) -> str | None:
    """Ids that spell the dates out (Duration_1_1_2019_To_12_31_2019_...) when no definition is parsed."""
    span = period_of(context)
    return period_key(span[0], span[1], None) if span else None


def period_key(start: str | None, end: str | None, instant: str | None) -> str | None:
    if instant:
        return f"@{instant}"
    if start and end:
        return f"{start}/{end}"
    return None


def _first(rx: re.Pattern, text: str) -> str | None:
    m = rx.search(text)
    return m.group(1) if m else None


def contexts(html: str) -> dict[str, str]:
    """Context id -> period_key, for undimensioned contexts only."""
    out = {}
    for cid, body in _CONTEXT.findall(html):
        if _DIMENSION.search(body):
            continue
        key = period_key(*(_first(rx, body) for rx in (_START, _END, _INSTANT)))
        if key:
            out[cid] = key
    return out


class _Parser(HTMLParser):
    def __init__(self, ctx: dict[str, str]) -> None:
        super().__init__(convert_charrefs=True)
        self._ctx = ctx
        self.pages: list[list[str]] = [[]]
        self.tags: list[Tagged] = []
        self._stack: list[dict] = []     # open elements: name, breaks, hidden, row
        self._hidden = 0                 # depth inside display:none or ix:header
        self._fig: dict | None = None    # open ix:nonFraction
        self._row: list[str] | None = None
        self._row_refs: list[tuple[Tagged, list[str]]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        a = dict(attrs)
        style = a.get("style", "") or ""
        breaks = bool(_BREAK.search(style))
        hidden = tag == "ix:header" or bool(_HIDDEN.search(style))
        if breaks and re.search(r"page-break-before", style, re.IGNORECASE) and self.pages[-1]:
            self.pages.append([])
        el = {"name": tag, "breaks": breaks and "after" in style.lower(), "hidden": hidden}
        if tag == "tr":
            self._row = []
            el["row"] = self._row
        if tag == "ix:nonfraction" and not self._hidden and not hidden:
            self._fig = {"name": a.get("name", ""), "context": a.get("contextref", ""),
                         "scale": int(a.get("scale") or 0), "negative": a.get("sign") == "-",
                         "chunks": [], "row": self._row}
            el["fig"] = self._fig
        self._stack.append(el)
        if hidden:
            self._hidden += 1

    def handle_endtag(self, tag: str) -> None:
        while self._stack:
            el = self._stack.pop()
            if el.get("hidden"):
                self._hidden -= 1
            if el.get("fig") is not None:
                f = el["fig"]
                text = " ".join("".join(f["chunks"]).split())
                if text and f["name"]:
                    period = self._ctx.get(f["context"]) or _legacy_key(f["context"])
                    t = Tagged(f["name"], f["context"], f["scale"], text, len(self.pages), "", period,
                               f["negative"])
                    self.tags.append(t)
                    if f["row"] is not None:
                        self._row_refs.append((t, f["row"]))
                self._fig = None
            if el["name"] == "tr":
                self._row = None
                self._flush_row(el["row"])
            if el["breaks"]:
                self.pages.append([])
            if el["name"] == tag:
                break

    def _flush_row(self, row: list[str]) -> None:
        text = " ".join(" ".join(row).split())
        for t, ref in self._row_refs:
            if ref is row:
                t.row = text
        self._row_refs = [(t, r) for t, r in self._row_refs if r is not row]

    def handle_data(self, data: str) -> None:
        # Zero-width spaces are layout padding in the filing; drop them so a quote matches the text a reader sees.
        data = data.replace("\u200b", "")
        if self._hidden or not data.strip():
            return
        if self._fig is not None:
            self._fig["chunks"].append(data)
        self.pages[-1].append(data)
        if self._row is not None:
            self._row.append(data)


def read_filing(html: str) -> tuple[list[RawPage], list[Tagged]]:
    p = _Parser(contexts(html))
    p.feed(html)
    p.close()
    pages = [RawPage(text=" ".join(" ".join(chunks).split()), label=f"p. {i}")
             for i, chunks in enumerate(p.pages, 1) if chunks]
    return pages, p.tags


def figures(tags: list[Tagged], concept: str, period: str) -> list[Tagged]:
    """Plain (not dimensional) figures for one concept at one period_key()."""
    return [t for t in tags if t.name == concept and t.row and t.period == period]
