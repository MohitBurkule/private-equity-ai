"""Retrieval eval on FinanceBench open-source sample: is the gold evidence page in top-k?

Scoped to the question's document (metadata-first, per ARCHITECTURE section 12).
FinanceBench is non-commercial: internal eval only. Page numbers are 0-based in
the source; converted to 1-based here.
Usage: python evals/run_retrieval_eval.py DATA_DIR [--dense]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.parse.pdf import extract_pages  # noqa: E402
from app.hybrid import CrossEncoderReranker, DenseRanker, HybridIndex  # noqa: E402
from app.search import PageIndex  # noqa: E402


def main(data: Path, ks=(1, 3, 5, 10)) -> dict:
    gold = [json.loads(line) for line in (data / "financebench_open_source.jsonl").open()]
    have = {p.stem: p for p in (data / "sec").glob("*.pdf")}
    pages, ids = [], {}
    for name, path in have.items():
        for p in extract_pages(path):
            pages.append((name, p.number, p.text))
        ids[name] = name
    results = {}
    variants = {'bm25': PageIndex(pages), 'hybrid': HybridIndex(pages)}
    if "--dense" in sys.argv:  # needs the `dense` extra and Hugging Face access for weights
        dense = DenseRanker(pages)
        variants['dense'] = dense
        variants['hybrid+dense'] = HybridIndex(pages, extra=[dense])
        variants['hybrid+dense+rerank'] = Reranked(variants['hybrid+dense'], CrossEncoderReranker(pages))
    for name, index in variants.items():
        results[name] = score(index, gold, have, ks)
    print(json.dumps(results))
    return results


class Reranked:
    """Fuse first, then rescore the top 30 candidates with a cross-encoder."""

    def __init__(self, base, reranker, depth: int = 30):
        self.base, self.reranker, self.depth = base, reranker, depth

    def search(self, query, k=5, doc_ids=None):
        return self.reranker.rerank(query, self.base.search(query, self.depth, doc_ids), k)


def score(index, gold, have, ks) -> dict:
    n, hit = 0, {k: 0 for k in ks}
    for g in gold:
        if g["doc_name"] not in have:
            continue
        want = {e["evidence_page_num"] + 1 for e in g["evidence"]}
        res = index.search(g["question"], k=max(ks), doc_ids={g["doc_name"]})
        n += 1
        for k in ks:
            if want & {h.page for h in res[:k]}:
                hit[k] += 1
    return {"n": n, **{f"recall@{k}": round(hit[k] / n, 3) for k in ks}}


if __name__ == "__main__":
    main(Path([a for a in sys.argv[1:] if not a.startswith('--')][0]))
