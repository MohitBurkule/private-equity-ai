"""Version diff for an IC memo: the current draft against a previous draft the reviewer keeps.

Compared line by line, so a changed figure shows as one line removed and one added. Nothing is stored
server side: the caller sends the previous text. Lines are kept verbatim, including their source notes.
"""
from __future__ import annotations

import difflib
import re


def diff_memos(previous: str, current: str) -> dict:
    a, b = previous.splitlines(), current.splitlines()
    added, removed, same = [], [], 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            same += i2 - i1
            continue
        removed += a[i1:i2]
        added += b[j1:j2]
    return {"unchanged": same, "added": [ln for ln in added if ln.strip()],
            "removed": [ln for ln in removed if ln.strip()], "changed": bool(added or removed)}


_NUMBER = re.compile(r"[-+(]?[$£€]?\d[\d,]*(?:\.\d+)?%?\)?")
_NOTE = re.compile(r"\[(\d+)\]")


def _body(line: str) -> str:
    """The line without its [n] source notes, so a note number is never read as a figure."""
    return _NOTE.sub("", line)


def _label(line: str) -> str:
    return " ".join(_NUMBER.sub(" # ", _body(line)).split())


def _readable(line: str, changed: set[int]) -> str:
    """The line as a reader wrote it, with only the changed figures replaced by an ellipsis. Years and other
    unchanged numbers stay, so 'Revenue FY2025' reads as itself."""
    i = 0

    def mask(m: re.Match) -> str:
        nonlocal i
        out = "…" if i in changed else m.group(0)
        i += 1
        return out

    return " ".join(_NUMBER.sub(mask, _body(line)).split()).lstrip("- ").strip()


def _numbers(line: str) -> list[str]:
    return _NUMBER.findall(_body(line))


def figure_changes(previous: str, current: str) -> dict:
    """What changed in figures and claims between two drafts, with the source notes on each side.

    A figure change is a line whose wording is the same once its numbers are masked, but whose numbers differ.
    Anything else that was added or removed is a claim change. Both sides keep their [n] note references, so a
    reader can open the source a changed number came from."""
    d = diff_memos(previous, current)
    removed = [ln for ln in d["removed"]]
    added = [ln for ln in d["added"]]
    figures, claim_removed = [], []
    unmatched_added = list(added)
    for old in removed:
        same_body = next((new for new in unmatched_added if _body(new) == _body(old)), None)
        if same_body is not None:  # only the source note moved: neither a figure nor a claim change
            unmatched_added.remove(same_body)
            continue
        match = next((new for new in unmatched_added
                      if _label(new) == _label(old) and _numbers(new) != _numbers(old)), None)
        if match is None:
            claim_removed.append(old)
            continue
        unmatched_added.remove(match)
        old_nums, new_nums = _numbers(old), _numbers(match)
        changed = {i for i, (a, b) in enumerate(zip(old_nums, new_nums)) if a != b}
        figures.append({"label": _readable(old, changed),
                        "from": [old_nums[i] for i in sorted(changed)],
                        "to": [new_nums[i] for i in sorted(changed)],
                        "notes_from": _NOTE.findall(old), "notes_to": _NOTE.findall(match)})
    return {"figure_changes": figures,
            "claim_changes": {"added": unmatched_added, "removed": claim_removed}}
