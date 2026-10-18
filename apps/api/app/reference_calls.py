"""Customer reference-call notes: turns by speaker, and the lines a reviewer should read first.

Text only: audio has to be transcribed before it gets here. The same turn format as expert calls (`Speaker: words`).
Two kinds of flag: the MNPI phrases a compliance reviewer checks on any call, and commercial phrases a deal team
reads for customer risk (churn, switching, pricing pushback). A flag is a prompt to read the turn, never a finding.
Nothing is stored; the transcript belongs to the caller.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.expert_calls import _MNPI_PHRASES, parse

_COMMERCIAL_PHRASES = (
    "switching", "switch to", "churn", "churned", "renewal", "not renewing", "price increase", "too expensive",
    "pricing pressure", "competitor", "evaluating alternatives", "budget cut", "lost the contract",
)


@dataclass
class Flag:
    line: int
    speaker: str
    kind: str  # mnpi | commercial
    phrase: str
    quote: str


def review(transcript: str) -> dict:
    turns = parse(transcript)
    out: list[Flag] = []
    for t in turns:
        lowered = t.text.lower()
        for kind, phrases in (("mnpi", _MNPI_PHRASES), ("commercial", _COMMERCIAL_PHRASES)):
            for phrase in phrases:
                if re.search(rf"\b{re.escape(phrase)}\b", lowered):
                    out.append(Flag(t.line, t.speaker, kind, phrase, t.text))
    return {"turns": len(turns), "speakers": sorted({t.speaker for t in turns}),
            "flags": [f.__dict__ for f in out]}
