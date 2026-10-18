"""Accuracy by document type. All items below are SYNTHETIC."""
from app.eval_report import doc_type, report

ITEMS = [
    {"id": "a", "sources": [{"type": "pdf"}]},
    {"id": "b", "sources": [{"type": "pdf"}, {"type": "pdf"}]},
    {"id": "c", "sources": [{"type": "xbrl"}]},
    {"id": "d", "sources": [{"type": "xbrl"}, {"type": "pdf"}]},
    {"id": "e", "doc_type": "ddq", "sources": [{"type": "pdf"}]},
]


def test_type_comes_from_field_then_sources_and_mixed_is_not_guessed():
    assert [doc_type(i) for i in ITEMS] == ["pdf", "pdf", "xbrl", "mixed", "ddq"]


def test_accuracy_counts_only_scored_items_and_unscored_gives_none():
    r = report(ITEMS, {"a": True, "b": False, "c": True})
    assert r["pdf"] == {"items": 2, "scored": 2, "correct": 1, "accuracy": 0.5}
    assert r["xbrl"] == {"items": 1, "scored": 1, "correct": 1, "accuracy": 1.0}
    assert r["mixed"] == {"items": 1, "scored": 0, "correct": 0, "accuracy": None}
