"""Due diligence questionnaire auto-answer from the firm's accepted rules. Pure code, no LLM.

A question is answered only when an accepted firm rule matches it: at least MIN_OVERLAP content words of the
question appear in the rule's label or hint, and one rule scores strictly higher than any other. The answer is
the rule's accepted value with its document, page and quote. Everything else is left unanswered with the reason.
Matching is word overlap, so a wrong answer is possible when the wording is close: reviewers read each one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.firm_knowledge import TERMS

MIN_OVERLAP = 2
STOP = {"the", "and", "for", "what", "does", "your", "with", "that", "this", "are", "how", "which", "from", "any",
        "firm", "fund", "have", "has", "will", "you", "its", "our", "who", "when", "all", "per", "into", "such"}
_WORD = re.compile(r"[a-z]{3,}")


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in STOP}


@dataclass(frozen=True)
class Question:
    id: str
    section: str
    text: str


def answer(questions: list[Question], accepted: dict[str, list[dict]]) -> list[dict]:
    """accepted: firm_knowledge.profile() output, key -> rows with value and source."""
    rules = [(t, accepted[t.key][-1]) for t in TERMS if accepted.get(t.key)]  # newest accepted row per key
    out = []
    for q in questions:
        qw = _words(q.text)
        scores = []
        for term, row in rules:
            overlap = qw & _words(f"{term.label} {term.hint}")
            scores.append((len(overlap), term, row, sorted(overlap)))
        scores.sort(key=lambda s: -s[0])
        best = scores[0] if scores else None
        tie = best is not None and len(scores) > 1 and scores[1][0] == best[0]
        if best is None or best[0] < MIN_OVERLAP or tie:
            reason = "no accepted firm rule matched" if (best is None or best[0] < MIN_OVERLAP) \
                else "two firm rules match equally; a person must choose"
            out.append({"id": q.id, "section": q.section, "question": q.text, "status": "unanswered",
                        "reason": reason})
            continue
        _, term, row, words = best
        out.append({"id": q.id, "section": q.section, "question": q.text, "status": "answered",
                    "answer": row["value"], "rule": term.key, "matched": words, "source": row["source"]})
    return out
