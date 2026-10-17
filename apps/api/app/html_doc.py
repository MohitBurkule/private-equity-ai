"""HTML filings (EDGAR .htm exhibits) split into text blocks that citations can point at.

HTML has no page numbers, so a citation names where the text sits instead: the section number and heading
it falls under, the element id when the filing has one, and the character offset of the block in the raw filing
otherwise. Nothing here assigns page numbers. Blocks are paragraphs, table rows and headings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from app.debt_parse import _AMOUNT, _FACILITY, _SENT

_BLOCK = frozenset({"p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "br"})
_SKIP = frozenset({"script", "style"})
_NBSP = re.compile(r"[   ]")
_SPACE = re.compile(r"\s+")
_SECTION = re.compile(r"(\d+\.\d+)\.\s+([A-Z][^.]{2,80}?)\s*\.?\s*$")
_DEFINED = re.compile(r"[“\"]\s*([^”\"]{1,60}?)\s*[”\"]\s+(?:means|shall mean)\b")
_SENTENCE_END = re.compile(r"\.(?=\s+[“\"A-Z]|\s*$)")
_SECTION_REF = re.compile(r"Section (\d+\.\d+)")
# A facility's amount is stated as its aggregate principal, not as a minimum, prepayment or increment.
_TOTAL = re.compile(r"aggregate principal amount not to exceed\s+\$", re.IGNORECASE)


@dataclass(frozen=True)
class Unit:
    idx: int
    section: str | None
    heading: str | None
    anchor: str | None
    offset: int
    text: str


class _Blocks(HTMLParser):
    """Offsets are taken from the parser's (line, column) position, mapped into the raw filing, so they index
    the same string the filing viewer highlights."""

    def __init__(self, raw: str) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str | None, int]] = []  # (text, anchor, offset of its opening tag)
        self._buf: list[str] = []
        self._anchor: str | None = None
        self._block_at = 0
        self._skip = 0
        self._line_starts = [0]
        for i, ch in enumerate(raw):
            if ch == "\n":
                self._line_starts.append(i + 1)

    def _abs(self) -> int:
        line, col = self.getpos()
        return self._line_starts[line - 1] + col

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip += 1
        ids = dict(attrs)
        found = ids.get("id") or (ids.get("name") if tag == "a" else None)
        if found and self._anchor is None:
            self._anchor = found
        if tag in _BLOCK:
            self._flush()
            self._block_at = self._abs()
        if tag == "td":
            self._buf.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip -= 1
        if tag in _BLOCK:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._buf.append(data)

    def _flush(self) -> None:
        text = _SPACE.sub(" ", _NBSP.sub(" ", "".join(self._buf))).strip()
        self._buf = []
        if text:
            self.blocks.append((text, self._anchor, self._block_at))
            self._anchor = None


def parse_units(data: bytes) -> list[Unit]:
    """Text blocks in document order. Section and heading are inherited by the blocks that follow a
    numbered heading, so a clause knows which section it sits in."""
    raw = data.decode("utf-8", errors="replace")
    p = _Blocks(raw)
    p.feed(raw)
    p._flush()
    units: list[Unit] = []
    section = heading = None
    for i, (text, anchor, offset) in enumerate(p.blocks):
        m = _SECTION.match(text)
        if m and len(text) <= 120:
            section, heading = m.group(1), m.group(2)
        units.append(Unit(idx=i, section=section, heading=heading, anchor=anchor, offset=offset, text=text))
    return units


def locate(unit: Unit) -> dict:
    """The citation fields for a unit. Anchor is None when the filing has no element id on that block."""
    return {"section": unit.section, "heading": unit.heading, "anchor": unit.anchor, "offset": unit.offset}


def sentence_at(text: str, start: int) -> str:
    """The sentence in `text` that contains `start`, ending at the first sentence end after it."""
    m = _SENTENCE_END.search(text, start)
    end = m.end() if m else len(text)
    return text[start:end].strip()


def defined_terms(units: list[Unit]) -> dict[str, tuple[int, str]]:
    """Defined term -> (unit index, defining sentence). First definition wins."""
    out: dict[str, tuple[int, str]] = {}
    for u in units:
        for m in _DEFINED.finditer(u.text):
            term = m.group(1)
            if term not in out:
                out[term] = (u.idx, sentence_at(u.text, m.start()))
    return out


def heading_for(units: list[Unit], section: str) -> Unit | None:
    """The unit that is the numbered heading of `section` ("2.1" -> "2.1. Term Loan A Facility ")."""
    # A table of contents repeats the number with a page figure ("2.1. Term Loan A Facility 59"); the body
    # heading ends with a full stop.
    for u in units:
        m = _SECTION.match(u.text)
        if m and m.group(1) == section and len(u.text) <= 120 and u.text.endswith("."):
            return u
    return None


def resolve_defined_facility(units: list[Unit], term: str, defs: dict[str, tuple[int, str]]) -> dict | None:
    """Follows a defined term to the facility it names: "Loans" means the loans under Section 2.1(a)(i), and
    Section 2.1 is headed "Term Loan A Facility". Returns the facility and the two units that establish it,
    or None when the chain does not end in a named facility (nothing is guessed)."""
    if term not in defs:
        return None
    def_idx, def_quote = defs[term]
    ref = _SECTION_REF.search(def_quote)
    if ref is None:
        return None
    head = heading_for(units, ref.group(1))
    if head is None:
        return None
    fac = _FACILITY.search(head.heading or "")
    if fac is None:
        return None
    return {"facility": fac.group(1), "sources": [(def_idx, def_quote), (head.idx, head.text)]}


def defined_facility_amounts(units: list[Unit]) -> list[dict]:
    """Facility amounts stated with a defined term, e.g. "...in the form of Loans in an aggregate principal
    amount not to exceed $500,000,000". The sentence names no facility, so the term is followed through
    its definition. The fact cites the amount sentence and the chain that names the facility."""
    defs = defined_terms(units)
    resolved = {t: r for t in defs if (r := resolve_defined_facility(units, t, defs)) is not None}
    out = []
    for u in units:
        for sent in _SENT.split(u.text):
            s = sent.strip()
            if _FACILITY.search(s) or not (_AMOUNT.search(s) and _TOTAL.search(s)):
                continue
            for term, r in resolved.items():
                if re.search(rf"\b{re.escape(term)}\b", s):
                    out.append({
                        "facility": r["facility"],
                        "amount": _AMOUNT.search(s).group(1).replace(",", ""),
                        "idx": u.idx,
                        "quote": s,
                        "extra_sources": r["sources"],
                    })
                    break
    return out
