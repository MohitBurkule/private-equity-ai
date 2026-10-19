"""Scoped BM25 over pages. Scope (document ids) is applied before ranking."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_TOK = re.compile(r"[a-z0-9][a-z0-9.,%$-]*", re.IGNORECASE)
_STOP = {
    "the", "of", "and", "to", "in", "a", "for", "is", "was", "what", "are", "did", "does",
    "by", "on", "as", "at", "an", "or", "be", "from", "with", "that", "this", "assume",
    "you", "analyst", "public", "equities", "answer", "following", "question", "primarily",
    "using", "information", "provided", "give", "response", "details", "shown", "statement",
    "usd", "millions", "fy", "has", "have", "any", "there", "their", "compare", "how",
    "who", "which", "where", "when", "it", "its", "if", "not", "useful", "metric",
}
# Finance vocabulary: question words -> the labels filings actually print.
SYNONYMS = {
    "capex": "purchases property plant equipment",
    "capital": "purchases property plant equipment",
    "ppne": "property plant equipment net",
    "ppe": "property plant equipment",
    "customers": "customer",
    "cyclicality": "cyclical cycles",
    "acquired": "acquisition acquire",
    "tax": "income taxes effective rate",
    "margin": "gross margin profit revenues cost",
    "legal": "legal proceedings litigation lawsuit",
    "liabilities": "liabilities total",
    "eps": "earnings per share",
    "revenue": "revenues sales",
}


# Financial statement pages (income statement, balance sheet, cash flows) carry their numbers in tables with few
# prose words, so BM25 ranks prose pages above them. A finance-sounding question gets those pages a boost.
STATEMENT_BOOST = 1.5
_STATEMENT = re.compile(r"Consolidated (Statements? of|Balance Sheets?)|Statements? of (Income|Operations|Cash Flows|Earnings)|Balance Sheets?", re.IGNORECASE)
_FINANCE = re.compile(r"revenue|sales|income|margin|tax|cash|capital|capex|earnings|net|operations|costs?|expenses?|assets|liabilities|dividend|debt|equity|profit|eps|share|growth|rate", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [t.lower().strip(".,") for t in _TOK.findall(text) if t.lower() not in _STOP]


def expand_query(query: str) -> list[str]:
    toks = tokenize(query)
    out = list(toks)
    for t in toks:
        if t in SYNONYMS:
            out.extend(tokenize(SYNONYMS[t]))
    return out


@dataclass(frozen=True)
class Hit:
    doc_id: str
    page: int
    score: float


class PageIndex:
    def __init__(self, pages: list[tuple[str, int, str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.keys = [(d, n) for d, n, _ in pages]
        self.tf = [Counter(tokenize(t)) for _, _, t in pages]
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = (sum(self.len) / len(self.len)) if self.len else 0.0
        df: Counter[str] = Counter()
        for c in self.tf:
            df.update(c.keys())
        n = len(pages)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.statement = [bool(_STATEMENT.search(t)) for _, _, t in pages]

    def search(self, query: str, k: int = 5, doc_ids: set[str] | None = None) -> list[Hit]:
        q = expand_query(query)
        boost = STATEMENT_BOOST if _FINANCE.search(query) else 1.0
        hits = []
        for i, (doc, page) in enumerate(self.keys):
            if doc_ids is not None and doc not in doc_ids:
                continue
            tf, dl, s = self.tf[i], self.len[i], 0.0
            for t in q:
                f = tf.get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (
                        f + self.k1 * (1 - self.b + self.b * dl / (self.avg or 1)))
            if s > 0:
                hits.append(Hit(doc, page, s * (boost if self.statement[i] else 1.0)))
        hits.sort(key=lambda h: -h.score)
        return hits[:k]
