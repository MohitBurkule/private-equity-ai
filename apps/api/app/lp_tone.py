"""Tone pass for LP letters: a local model rewrites the narrative sentences in the firm's LP tone.

The model never sees a number. Every figure in a sentence is replaced by a token ([[1]], [[2]], ...) before
the call and put back after it. A rewrite is kept only when it returns the same paragraphs, every token exactly
once and in the same order, and no digit outside a token. Any other output is rejected and the neutral letter
is kept, with the reason recorded on the letter.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.lp_docs import Model

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?(?:%|x)?")
TOKEN = re.compile(r"\[\[(\d+)\]\]")
SYSTEM = (
    "You rewrite sentences of an LP letter in the tone described. Keep every token of the form [[n]] exactly as "
    "written, once, in the same order. Add no numbers, no new facts and no tokens. Reply with JSON only: "
    '{"paragraphs":[{"id":"...","text":"..."}]} with the same ids.'
)


@dataclass
class Style:
    status: str  # applied | rejected | not_requested
    reason: str = ""


def mask(text: str) -> tuple[str, list[str]]:
    values: list[str] = []

    def hide(m: re.Match) -> str:
        values.append(m.group(0))
        return f"[[{len(values)}]]"

    return NUMBER.sub(hide, text), values


def unmask(text: str, values: list[str]) -> str:
    return TOKEN.sub(lambda m: values[int(m.group(1)) - 1], text)


def _check(original: str, rewritten: str) -> str | None:
    """None when the rewrite is safe; otherwise the reason it is refused."""
    if TOKEN.findall(rewritten) != TOKEN.findall(original):
        return "tokens changed, dropped, repeated or reordered"
    if NUMBER.search(TOKEN.sub("", rewritten)):
        return "a number appeared outside the cited figures"
    return None


def rewrite(model: Model, tone: str, llm) -> tuple[Model, Style]:
    """Rewrites single-part narrative paragraphs. Multi-part paragraphs (the cited flows) stay as they are."""
    targets = {}
    payload = []
    for i, p in enumerate(model.paragraphs):
        if len(p) == 1 and p[0][0]:
            masked, values = mask(p[0][0])
            targets[str(i)] = (masked, values)
            payload.append({"id": str(i), "text": masked})
    if not payload:
        return model, Style("not_requested", "no narrative sentences to rewrite")
    prompt = f"Tone: {tone}\n\n{json.dumps({'paragraphs': payload}, ensure_ascii=False)}"
    try:
        out = json.loads(llm.complete(SYSTEM, prompt))
        got = {str(p["id"]): str(p["text"]) for p in out["paragraphs"]}
    except (ValueError, KeyError, TypeError) as e:
        return model, Style("rejected", f"unreadable model output ({type(e).__name__})")
    if set(got) != set(targets):
        return model, Style("rejected", "paragraph ids changed")
    new = [list(p) for p in model.paragraphs]
    for pid, (masked, values) in targets.items():
        reason = _check(masked, got[pid])
        if reason:
            return model, Style("rejected", reason)
        i = int(pid)
        new[i] = [(unmask(got[pid], values), new[i][0][1])]
    out_model = Model(model.title, [list(p) for p in new], model.sources)
    return out_model, Style("applied")
