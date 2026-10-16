"""Inline XBRL (iXBRL) reader for UK Companies House accounts, with balance-sheet arithmetic checks.

Companies House accounts are filed by tiny companies and often contain errors, so we recompute the
identities before trusting any figure: fixed + net current = total assets less current liabilities,
net assets = equity. A failing identity makes the filing `reliable=False`: callers must flag it,
not answer from it. Only non-dimensional contexts are used for headline figures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser


@dataclass
class Fact:
    name: str  # local name without prefix, e.g. FixedAssets
    context: str
    value: Decimal


@dataclass
class Ctx:
    instant: str | None = None
    start: str | None = None
    end: str | None = None
    dimensional: bool = False


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.contexts: dict[str, Ctx] = {}
        self.facts: list[Fact] = []
        self._ctx_id: str | None = None
        self._tag_text: str | None = None
        self._cur: dict | None = None
        self._buf: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "xbrli:context":
            self._ctx_id = a.get("id")
            self.contexts[self._ctx_id or ""] = Ctx()
        elif tag in ("xbrli:instant", "xbrli:startdate", "xbrli:enddate"):
            self._tag_text = tag
            self._buf = []
        elif tag.startswith("xbrldi:") and self._ctx_id:
            self.contexts[self._ctx_id].dimensional = True
        elif tag == "ix:nonfraction":
            if self._cur is None:
                self._cur, self._buf, self._depth = a, [], 0
            else:
                self._depth += 1

    def handle_endtag(self, tag):
        if tag == "xbrli:context":
            self._ctx_id = None
        elif tag in ("xbrli:instant", "xbrli:startdate", "xbrli:enddate") and self._ctx_id:
            c, v = self.contexts[self._ctx_id], "".join(self._buf).strip()
            if tag == "xbrli:instant":
                c.instant = v
            elif tag == "xbrli:startdate":
                c.start = v
            else:
                c.end = v
            self._tag_text = None
        elif tag == "ix:nonfraction" and self._cur is not None:
            if self._depth:
                self._depth -= 1
                return
            a, text = self._cur, "".join(self._buf).strip()
            self._cur = None
            f = _to_fact(a, text)
            if f:
                self.facts.append(f)

    def handle_data(self, data):
        if self._tag_text is not None or self._cur is not None:
            self._buf.append(data)


def _to_fact(a: dict, text: str) -> Fact | None:
    fmt = (a.get("format") or "").lower()
    cleaned = text.replace(",", "").replace(" ", "")
    if "zerodash" in fmt or cleaned in ("-", "—", "–", ""):
        val = Decimal(0)
    else:
        try:
            val = Decimal(cleaned)
        except InvalidOperation:
            return None
    val *= Decimal(10) ** int(a.get("scale") or 0)
    if a.get("sign") == "-":
        val = -val
    return Fact((a.get("name") or "").split(":")[-1], a.get("contextref") or "", val)


@dataclass
class Report:
    facts: dict[str, Decimal] = field(default_factory=dict)  # headline figures, latest instant
    instant: str | None = None
    checks: dict[str, bool | None] = field(default_factory=dict)
    reliable: bool = True


def read_ixbrl(html: str) -> Report:
    p = _Parser()
    p.feed(html)
    # latest non-dimensional balance-sheet instant that has balance-sheet items
    balance = {"FixedAssets", "CurrentAssets", "NetCurrentAssetsLiabilities",
               "TotalAssetsLessCurrentLiabilities", "NetAssetsLiabilities", "Equity"}
    insts = sorted({p.contexts[f.context].instant for f in p.facts
                    if f.name in balance and f.context in p.contexts
                    and p.contexts[f.context].instant and not p.contexts[f.context].dimensional})
    rep = Report()
    if not insts:
        rep.checks = {"fixed+netcurrent=TALCL": None, "netassets=equity": None}
        return rep
    rep.instant = insts[-1]
    for f in p.facts:
        c = p.contexts.get(f.context)
        if c and c.instant == rep.instant and not c.dimensional and f.name in balance:
            rep.facts.setdefault(f.name, f.value)
    g = rep.facts.get
    fa, nca, talcl = g("FixedAssets"), g("NetCurrentAssetsLiabilities"), g("TotalAssetsLessCurrentLiabilities")
    na, eq = g("NetAssetsLiabilities"), g("Equity")
    # a missing FixedAssets tag means no fixed assets reported: treat as 0 only when both others exist
    if talcl is not None and nca is not None:
        rep.checks["fixed+netcurrent=TALCL"] = (fa or Decimal(0)) + nca == talcl
    if na is not None and eq is not None:
        rep.checks["netassets=equity"] = na == eq
    rep.reliable = all(v is not False for v in rep.checks.values())
    return rep
