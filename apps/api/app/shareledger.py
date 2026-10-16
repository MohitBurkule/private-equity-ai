"""Reconcile a company's issued share total across Companies House capital events (SH01, SH02, SH19).

Each form states a total *after* its event, but forms filed for the same date are often stated against
the same prior base, so their totals are not cumulative. The ledger keeps one running total:
  * an allotment whose stated total equals running + allotted is cumulative;
  * same-date allotments that each equal base + own allotted are 'same_base' and are combined;
  * a consolidation must start from the running total and gives the ratio;
  * a statement (e.g. SH19) must equal the running total;
  * on one day: statements first, then allotments, then a consolidation.
Anything that fits none of these is reported as `unreconciled` with the gap. Nothing is guessed, and
the running total does not move on an unreconciled event.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from itertools import groupby


@dataclass
class Event:
    kind: str  # allot | statement | consolidate
    date: str  # ISO date of the event
    source: str  # form reference for citation
    allotted: Decimal | None = None
    total_after: Decimal | None = None
    old_total: Decimal | None = None  # consolidate only


@dataclass
class Entry:
    source: str
    date: str
    kind: str
    status: str  # opening | cumulative | same_base | statement_ok | consolidated | unreconciled
    running_after: Decimal
    detail: str = ""


@dataclass
class Ledger:
    entries: list[Entry] = field(default_factory=list)
    running: Decimal | None = None
    problems: list[str] = field(default_factory=list)


def reconcile(opening: Decimal, opening_source: str, events: list[Event]) -> Ledger:
    led = Ledger(running=opening)
    led.entries.append(Entry(opening_source, "", "opening", "opening", opening))
    for ev in events:
        date.fromisoformat(ev.date)
    ordered = sorted(events, key=lambda e: e.date)
    for _, grp in groupby(ordered, key=lambda e: e.date):
        group = list(grp)
        # within one day: statements describe the start, then allotments, then a consolidation
        for e in group:
            if e.kind == "statement":
                _statement(led, e)
        allots = [e for e in group if e.kind == "allot"]
        if allots:
            _allot_group(led, led.running, allots)
        for e in group:
            if e.kind == "consolidate":
                _consolidate(led, e)
    return led


def _consolidate(led: Ledger, e: Event) -> None:
    if e.old_total is None or e.total_after is None or e.total_after <= 0:
        _bad(led, e, "consolidation needs old_total and a positive total_after")
    elif e.old_total != led.running:
        _bad(led, e, f"consolidation starts from {e.old_total}, ledger has {led.running}")
    elif e.old_total % e.total_after:
        _bad(led, e, f"{e.old_total} / {e.total_after} is not a whole ratio")
    else:
        led.running = e.total_after
        led.entries.append(Entry(e.source, e.date, e.kind, "consolidated", led.running,
                                 f"{e.old_total / e.total_after:f}-for-1"))


def _statement(led: Ledger, e: Event) -> None:
    if e.total_after == led.running:
        led.entries.append(Entry(e.source, e.date, e.kind, "statement_ok", led.running))
    else:
        _bad(led, e, f"states {e.total_after}, ledger has {led.running}")


def _allot_group(led: Ledger, base: Decimal, allots: list[Event]) -> None:
    ok = [e for e in allots if e.allotted is not None and e.total_after is not None]
    for e in allots:
        if e not in ok:
            _bad(led, e, "allotment needs allotted and total_after")
    same = [e for e in ok if e.total_after == base + e.allotted]
    if len(ok) == 1 and ok[0] in same:
        led.running = base + ok[0].allotted
        led.entries.append(Entry(ok[0].source, ok[0].date, "allot", "cumulative", led.running))
        return
    if len(ok) > 1 and len(same) == len(ok):
        led.running = base + sum(e.allotted for e in ok)
        for e in ok:
            led.entries.append(Entry(e.source, e.date, "allot", "same_base", led.running,
                                     f"stated {e.total_after} against base {base}; combined total {led.running}"))
        return
    for e in ok:
        _bad(led, e, f"states {e.total_after}; base {base} + allotted {e.allotted} = {base + e.allotted}")


def _bad(led: Ledger, e: Event, why: str) -> None:
    led.problems.append(f"{e.source}: {why}")
    led.entries.append(Entry(e.source, e.date, e.kind, "unreconciled", led.running, why))
