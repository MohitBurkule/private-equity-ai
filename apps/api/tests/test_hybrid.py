from app.hybrid import CharNgramRanker, HybridIndex, rrf
from app.search import Hit

PAGES = [
    ("a", 1, "legal proceedings and litigation"),
    ("a", 2, "purchases of property plant and equipment 1,577"),
    ("b", 1, "purchases of property plant and equipment 9,999"),
]


def test_rrf_prefers_items_ranked_well_by_both():
    r1 = [Hit("a", 1, 0), Hit("a", 2, 0)]
    r2 = [Hit("a", 2, 0), Hit("a", 1, 0)]
    r3 = [Hit("a", 2, 0)]
    assert rrf([r1, r2, r3], k=2)[0].page == 2


def test_char_ngram_survives_typo_and_respects_scope():
    r = CharNgramRanker(PAGES)
    hits = r.search("purchasez of propertty plant", 5, {"a"})
    assert [(h.doc_id, h.page) for h in hits][:1] == [("a", 2)]
    assert all(h.doc_id == "a" for h in hits)


def test_hybrid_scoped():
    h = HybridIndex(PAGES).search("capex", k=3, doc_ids={"b"})
    assert [(x.doc_id, x.page) for x in h] == [("b", 1)]
