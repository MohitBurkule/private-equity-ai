"""Hybrid retrieval: BM25 + a second ranker fused with Reciprocal Rank Fusion (RRF).

The second ranker is pluggable (`Ranker` protocol). `CharNgramRanker` is a dependency-free
sparse char-trigram TF-IDF cosine ranker (robust to morphology/typos, no model download).
Dense embedding rankers (OpenAI, sentence-transformers, ...) implement the same protocol;
they are not evaluated yet because model weights are not reachable from the build sandbox.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Protocol

from app.search import Hit, PageIndex, expand_query


class Ranker(Protocol):
    def search(self, query: str, k: int, doc_ids: set[str] | None) -> list[Hit]: ...


def _grams(text: str, n: int = 3) -> Counter[str]:
    t = " ".join(text.lower().split())
    return Counter(t[i:i + n] for i in range(max(0, len(t) - n + 1)))


class CharNgramRanker:
    def __init__(self, pages: list[tuple[str, int, str]]):
        self.keys = [(d, p) for d, p, _ in pages]
        self.vecs = [_grams(t) for _, _, t in pages]
        df: Counter[str] = Counter()
        for v in self.vecs:
            df.update(v.keys())
        n = len(pages)
        self.idf = {g: math.log(1 + n / f) for g, f in df.items()}
        self.norms = [self._norm(v) for v in self.vecs]

    def _norm(self, v: Counter[str]) -> float:
        return math.sqrt(sum((c * self.idf.get(g, 0.0)) ** 2 for g, c in v.items())) or 1.0

    def search(self, query: str, k: int, doc_ids: set[str] | None) -> list[Hit]:
        q = _grams(" ".join(expand_query(query)))
        qn = self._norm(q)
        hits = []
        for i, (doc, page) in enumerate(self.keys):
            if doc_ids is not None and doc not in doc_ids:
                continue
            v = self.vecs[i]
            dot = sum(c * self.idf.get(g, 0.0) * v.get(g, 0) * self.idf.get(g, 0.0)
                      for g, c in q.items() if g in v)
            if dot > 0:
                hits.append(Hit(doc, page, dot / (qn * self.norms[i])))
        hits.sort(key=lambda h: -h.score)
        return hits[:k]


def rrf(rankings: list[list[Hit]], k: int = 10, c: int = 60) -> list[Hit]:
    score: dict[tuple[str, int], float] = {}
    for r in rankings:
        for rank, h in enumerate(r, 1):
            score[(h.doc_id, h.page)] = score.get((h.doc_id, h.page), 0.0) + 1.0 / (c + rank)
    fused = [Hit(d, p, s) for (d, p), s in score.items()]
    fused.sort(key=lambda h: -h.score)
    return fused[:k]


class HybridIndex:
    def __init__(self, pages: list[tuple[str, int, str]], extra: list[Ranker] | None = None):
        self.bm25 = PageIndex(pages)
        self.rankers: list[Ranker] = [CharNgramRanker(pages), *(extra or [])]

    def search(self, query: str, k: int = 5, doc_ids: set[str] | None = None, depth: int = 50) -> list[Hit]:
        lists = [self.bm25.search(query, depth, doc_ids)]
        lists += [r.search(query, depth, doc_ids) for r in self.rankers]
        return rrf(lists, k)
