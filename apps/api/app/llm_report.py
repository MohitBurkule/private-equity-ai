"""Per-model language-model report for one tenant over a number of days: calls, characters, mean and worst latency.
Reads the call log that CappedLLM writes. Pure over the rows it is given, so it is testable without a model."""
from __future__ import annotations

from collections import defaultdict
from statistics import mean


def summarise(rows: list[tuple[str, int, int, int]]) -> list[dict]:
    """rows are (model, chars_in, chars_out, latency_ms). One dict per model, busiest first."""
    by_model: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for model, cin, cout, ms in rows:
        by_model[model].append((cin, cout, ms))
    out = []
    for model, calls in by_model.items():
        out.append({
            "model": model,
            "calls": len(calls),
            "chars_in": sum(c[0] for c in calls),
            "chars_out": sum(c[1] for c in calls),
            "latency_ms_mean": round(mean(c[2] for c in calls)),
            "latency_ms_max": max(c[2] for c in calls),
        })
    return sorted(out, key=lambda r: (-r["calls"], r["model"]))
