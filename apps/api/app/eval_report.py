"""Accuracy by document type for the golden sets. Pure: takes golden items and a results map, returns the table.

A golden item's document type comes from its own `doc_type` field when it has one. Otherwise it is inferred from
its sources: a PDF or narrative doc is "pdf", an XBRL fact is "xbrl", inline XBRL is "ixbrl", HTML is "html". An item
whose sources disagree is "mixed", so it is reported on its own line rather than guessed into one type.
Results map item id -> True (answered correctly), False (wrong) or missing (not scored: counted as not run)."""
from __future__ import annotations

from collections import defaultdict

_BY_SOURCE = {"pdf": "pdf", "xbrl": "xbrl", "ixbrl": "ixbrl", "html": "html"}


def doc_type(item: dict) -> str:
    if item.get("doc_type"):
        return str(item["doc_type"])
    kinds = {_BY_SOURCE.get(s.get("type"), "other") for s in item.get("sources", [])}
    if not kinds:
        return "other"
    return kinds.pop() if len(kinds) == 1 else "mixed"


def report(items: list[dict], results: dict[str, bool]) -> dict[str, dict[str, float | int]]:
    """Per document type: items, scored, correct, and accuracy over the scored ones (None when nothing was scored)."""
    rows: dict[str, dict] = defaultdict(lambda: {"items": 0, "scored": 0, "correct": 0})
    for item in items:
        t = doc_type(item)
        rows[t]["items"] += 1
        if item["id"] in results:
            rows[t]["scored"] += 1
            rows[t]["correct"] += bool(results[item["id"]])
    for r in rows.values():
        r["accuracy"] = round(r["correct"] / r["scored"], 4) if r["scored"] else None
    return dict(sorted(rows.items()))
