"""One run over an uploaded document: legal red flags, LBO returns and the IC memo deck, each step reported with its
own status. Nothing is invented: a step that lacks its inputs is reported as skipped with the reason, and every figure
it produces carries the source it came from. An LBO input may be a labelled assumption (no document), and the output
lists those separately so they are never mistaken for document figures.

Extraction, comps and precedents need their own runs (an LLM job, peer data and an EDGAR scan) and are reported as
skipped here until those are supplied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app import lbo as lbo_mod


@dataclass
class Step:
    name: str
    status: str  # ok | skipped | failed
    reason: str = ""
    result: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"step": self.name, "status": self.status, "reason": self.reason, "result": self.result}


def lbo_inputs(raw: dict, doc_id: str) -> tuple[dict[str, lbo_mod.Cited], list[str]]:
    """Cited inputs from the request. An input is {value, source} from this document, or {value, assumption: label}.
    Returns the inputs and the names of the assumptions, so the output can list them apart."""
    out: dict[str, lbo_mod.Cited] = {}
    assumed: list[str] = []
    for name, spec in raw.items():
        try:
            value = Decimal(str(spec["value"]))
        except (KeyError, InvalidOperation, TypeError) as e:
            raise ValueError(f"{name}: needs a numeric value") from e
        if spec.get("assumption"):
            out[name] = lbo_mod.Cited(value, {"assumption": str(spec["assumption"])})
            assumed.append(name)
        elif spec.get("source"):
            src = dict(spec["source"])
            if src.get("document_id") != doc_id:
                raise ValueError(f"{name}: source must be this document")
            out[name] = lbo_mod.Cited(value, src)
        else:
            raise ValueError(f"{name}: needs a source or a labelled assumption")
    return out, assumed


def lbo_step(raw: dict, doc_id: str) -> Step:
    if not raw:
        return Step("lbo", "skipped", "no LBO inputs supplied (entry EBITDA, multiples, leverage and so on)")
    try:
        inputs, assumed = lbo_inputs(raw, doc_id)
    except ValueError as e:
        return Step("lbo", "failed", str(e))
    gap = lbo_mod.missing(inputs)
    if gap:
        return Step("lbo", "skipped", f"missing inputs: {', '.join(gap)}")
    try:
        r = lbo_mod.run(inputs)
    except ValueError as e:
        return Step("lbo", "failed", str(e))
    return Step("lbo", "ok", result={
        "moic": str(r.moic), "irr": None if r.irr is None else str(r.irr), "entry_ev": str(r.entry_ev),
        "sponsor_equity": str(r.equity), "exit_equity": str(r.exit_equity), "assumptions": assumed,
        "inputs": {k: {"value": str(c.value), "source": c.source} for k, c in inputs.items()}})


def legal_step(pages: list[tuple[int, str]], doc_id: str, doc_type: str | None, legal_mod) -> Step:
    if not doc_type:
        return Step("legal", "skipped", "no document type given (nda, spa or credit)")
    try:
        out = legal_mod.extract(pages, doc_type)
    except ValueError as e:
        return Step("legal", "failed", str(e))
    flags = legal_mod.red_flags(out)
    for f in flags:
        f.setdefault("document_id", doc_id)
    return Step("legal", "ok", result={"red_flags": flags, "absent": out.get("absent", [])})
