"""Version diff for an IC memo: the current draft against a previous draft the reviewer keeps.

Compared line by line, so a changed figure shows as one line removed and one added. Nothing is stored
server side: the caller sends the previous text. Lines are kept verbatim, including their source notes.
"""
from __future__ import annotations

import difflib


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
