"""Draft follow-up questions for management and the seller, from what is still outstanding on a deal.

Drafts only: nothing is sent or recorded. A draft comes from the open request list and the unanswered questions,
with fixed wording, so every draft points at a line that is really open. No model writes these.
"""
from __future__ import annotations


def drafts(open_requests: list[str], unanswered: list[str]) -> list[dict]:
    """One draft per open request ("please provide ...") and per unanswered question (a chaser). Order is kept."""
    out = [{"kind": "request", "text": f"Please provide {title}."} for title in open_requests]
    out += [{"kind": "chaser", "text": f"Following up on our earlier question: {q}"} for q in unanswered]
    return out
