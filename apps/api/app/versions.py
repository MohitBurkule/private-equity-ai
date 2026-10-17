"""Version lineage from filenames: `model_v3.xlsx` and `model_v5.xlsx` are one model at two points in time.

Why filenames: a data room carries version numbers in names, not in metadata, and the reviewer sees the name first.
This only reports which document supersedes which; it never picks a winner for a figure, because a newer model can
still carry an old input the reviewer has not changed.
"""
from __future__ import annotations

import re
from pathlib import PurePath

_VERSION = re.compile(r"[ _-]?(?:v|ver|version)[ _-]?(\d+(?:[._]\d+)*)", re.IGNORECASE)


def split_version(filename: str) -> tuple[str, tuple[int, ...] | None]:
    """(base name without the version token, version tuple). Version is None when the name has none."""
    stem = PurePath(filename).stem
    m = _VERSION.search(stem)
    if not m:
        return stem.lower(), None
    base = (stem[: m.start()] + stem[m.end():]).strip(" _-").lower()
    return base, tuple(int(x) for x in re.split(r"[._]", m.group(1)))


def superseded(filenames: dict[int, str]) -> dict[int, int]:
    """Maps each document id to the id of the newest same-lineage document that supersedes it. Documents with
    no version token, or a lineage with a single member, are never superseded."""
    groups: dict[str, list[tuple[tuple[int, ...], int]]] = {}
    for doc_id, name in filenames.items():
        base, ver = split_version(name)
        if ver is not None:
            groups.setdefault(base, []).append((ver, doc_id))
    out: dict[int, int] = {}
    for members in groups.values():
        newest_ver, newest_id = max(members)
        for ver, doc_id in members:
            if ver < newest_ver:
                out[doc_id] = newest_id
    return out
