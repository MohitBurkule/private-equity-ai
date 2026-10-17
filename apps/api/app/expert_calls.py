"""Expert-call transcripts: who said what, and where a turn may carry material non-public information.

A transcript is plain text with one turn per line, `Speaker: words`. Flags are phrase matches that a compliance
reviewer reads first. A flag means "look at this turn"; it is not a finding that the call broke a rule, because a
phrase match cannot tell an expert describing public news from one describing an unannounced deal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_TURN = re.compile(r"^\s*([A-Z][A-Za-z .'-]{0,60}?)\s*:\s*(.+?)\s*$")

# Phrases that usually mark non-public information. Lower-case, matched on word boundaries.
_MNPI_PHRASES = (
    "not yet announced", "not yet public", "unannounced", "pending transaction", "in talks to acquire",
    "in talks to sell", "internal forecast", "internal budget", "board minutes", "board approved",
    "under nda", "under an nda", "confidential", "non-public", "nonpublic", "before the announcement",
    "ahead of the announcement", "insider",
)


@dataclass
class Turn:
    line: int  # 1-based line in the transcript
    speaker: str
    text: str


@dataclass
class Flag:
    line: int
    speaker: str
    phrase: str
    quote: str


def parse(transcript: str) -> list[Turn]:
    """Turns in order. Lines without a `Speaker:` prefix continue the previous turn, so wrapped text is kept."""
    turns: list[Turn] = []
    for n, raw in enumerate(transcript.splitlines(), 1):
        if not raw.strip():
            continue
        m = _TURN.match(raw)
        if m:
            turns.append(Turn(n, m.group(1).strip(), m.group(2)))
        elif turns:
            turns[-1].text += " " + raw.strip()
    return turns


def flags(turns: list[Turn]) -> list[Flag]:
    out = []
    for t in turns:
        lowered = t.text.lower()
        for phrase in _MNPI_PHRASES:
            if re.search(rf"\b{re.escape(phrase)}\b", lowered):
                out.append(Flag(t.line, t.speaker, phrase, t.text))
    return out
