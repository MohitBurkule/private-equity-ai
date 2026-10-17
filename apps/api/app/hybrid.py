"""Hybrid retrieval: BM25 + a second ranker fused with Reciprocal Rank Fusion (RRF).

The second ranker is pluggable (`Ranker` protocol). `CharNgramRanker` is a dependency-free
sparse char-trigram TF-IDF cosine ranker (robust to morphology/typos, no model download).
Dense embedding rankers (OpenAI, sentence-transformers, ...) implement the same protocol;
they are not evaluated yet because model weights are not reachable from the build sandbox.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter, OrderedDict
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


_CACHE: OrderedDict[str, HybridIndex] = OrderedDict()  # dense embeddings are costly: reuse per page set


def default_index(pages: list[tuple[str, int, str]]) -> HybridIndex:
    """The retriever the product uses: BM25 + char-trigram + dense (bge-small) fused with RRF.

    Falls back to the lexical pair when fastembed is not installed. The cross-encoder rerank is
    not in the default: the eval showed it hurts recall@1/3/5 on the golden set.
    """
    key = hashlib.sha256(repr(pages).encode()).hexdigest()
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    extra: list[Ranker] = []
    if pages:
        try:
            extra.append(DenseRanker(pages))
        except ImportError:  # the `dense` extra is not installed
            pass
    _CACHE[key] = HybridIndex(pages, extra)
    while len(_CACHE) > 4:
        _CACHE.popitem(last=False)
    return _CACHE[key]


_EMBEDDERS: dict[str, object] = {}


def _embedder(model: str):
    """One ONNX session per model name, shared by every index. Each cached index used to load its own
    session (~0.3 GB apiece), so four cached documents held gigabytes of duplicate weights."""
    if model not in _EMBEDDERS:
        from fastembed import (
            TextEmbedding,  # lazy: only required when dense retrieval is used
        )
        _EMBEDDERS[model] = TextEmbedding(model)
    return _EMBEDDERS[model]


class DenseRanker:
    """Dense retrieval with a small open ONNX embedding model (fastembed, no torch, no API key).

    Pages are embedded once at construction; scope is applied before ranking. Needs the `dense`
    extra and the model weights from Hugging Face on first use (cached afterwards).
    """

    def __init__(self, pages: list[tuple[str, int, str]], model: str = "BAAI/bge-small-en-v1.5"):
        import numpy as np
        self.np = np
        self.model = _embedder(model)
        self.keys = [(d, p) for d, p, _ in pages]
        # batch_size: the default (256) peaks near 3.4 GB on 160 real pages; 16 peaks near 0.8 GB.
        self.vecs = np.array(list(self.model.embed([t[:4000] for _, _, t in pages], batch_size=16)), dtype="float32")

    def search(self, query: str, k: int, doc_ids: set[str] | None) -> list[Hit]:
        q = next(iter(self.model.query_embed(query)))
        sims = self.vecs @ q  # bge vectors are unit length
        order = self.np.argsort(-sims)
        out: list[Hit] = []
        for i in order:
            d, p = self.keys[i]
            if doc_ids is None or d in doc_ids:
                out.append(Hit(d, p, float(sims[i])))
                if len(out) == k:
                    break
        return out


class CrossEncoderReranker:
    """Rescore the top fused candidates with a small cross-encoder (fastembed, ONNX)."""

    def __init__(self, pages: list[tuple[str, int, str]], model: str = "Xenova/ms-marco-MiniLM-L-6-v2"):
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        self.model = TextCrossEncoder(model)
        self.text = {(d, p): t for d, p, t in pages}

    def rerank(self, query: str, hits: list[Hit], k: int) -> list[Hit]:
        if not hits:
            return []
        scores = list(self.model.rerank(query, [self.text[(h.doc_id, h.page)][:3000] for h in hits]))
        ranked = sorted(zip(hits, scores), key=lambda x: -x[1])
        return [Hit(h.doc_id, h.page, float(s)) for h, s in ranked[:k]]
