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


def derive_ebitda(steps: list[Step], doc_id: str, filename: str) -> dict | None:
    """EBITDA = verified operating income + verified depreciation and amortization, both from this filing's own tags.
    Returned as an LBO input spec whose quote names the two rows it was added from. None unless both are verified."""
    ext = next((s for s in steps if s.name == "extraction" and s.status == "ok"), None)
    if ext is None:
        return None
    got = {c["metric"]: c for c in ext.result.get("created", [])}
    if "operating_income" not in got or "depreciation_amortization" not in got:
        return None
    oi, da = got["operating_income"], got["depreciation_amortization"]
    value = Decimal(oi["value"]) + Decimal(da["value"])
    return {"value": str(value), "source": {"document_id": doc_id, "filename": filename, "page": oi["page"],
                                            "quote": f"derived: {oi['quote']} + {da['quote']}"}}


def crosscheck_step(extraction: Step | None, cik: str | None, fetch) -> Step:
    """Each extracted figure against the SEC's companyfacts value for the same concept and fiscal year end.
    A figure that differs is a data conflict: both values are listed, and the step fails until someone reads both."""
    from app import edgar
    from app.ixbrl_facts import BALANCE, CONCEPTS

    if extraction is None or extraction.status != "ok":
        return Step("crosscheck", "skipped", "needs verified extraction figures")
    if not cik:
        return Step("crosscheck", "skipped", "needs the entity's CIK to read companyfacts")
    period_end = extraction.result.get("period_end")
    try:
        facts = edgar.fetch_companyfacts(cik, fetch)
    # RuntimeError is the missing SEC_USER_AGENT case: reported as a failed step so the memo still returns.
    except (OSError, ValueError, RuntimeError) as e:
        return Step("crosscheck", "failed", f"companyfacts unavailable: {e}")
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    matched, conflicts, unchecked = [], [], []
    for c in extraction.result.get("created", []):
        metric = c["metric"]
        sec = None
        # the concept the extraction read, so the check compares like with like
        for concept in ([c["concept"]] if c.get("concept") else CONCEPTS[metric]):
            for entry in us_gaap.get(concept, {}).get("units", {}).get("USD", []):
                durational = "start" in entry
                if entry.get("end") == period_end and entry.get("form") == "10-K" and durational == (metric not in BALANCE):
                    sec = {"concept": concept, "value": entry["val"], "end": period_end}
                    break
            if sec:
                break
        if sec is None:
            unchecked.append({"metric": metric, "reason": f"no 10-K companyfacts value for {period_end}"})
            continue
        ours, theirs = Decimal(c["value"]), Decimal(str(sec["value"]))
        row = {"metric": metric, "extracted": str(ours), "companyfacts": str(theirs), "concept": sec["concept"]}
        (matched if ours == theirs else conflicts).append(row)
    if conflicts:
        return Step("crosscheck", "failed", f"{len(conflicts)} data conflict(s): extracted figures differ from companyfacts",
                    result={"matched": matched, "conflicts": conflicts, "unchecked": unchecked})
    return Step("crosscheck", "ok", result={"matched": matched, "conflicts": [], "unchecked": unchecked})


# Words that mark a document's type in its first pages. A filing or memo that names none of them is not
# read as a contract, so legal is skipped rather than run on the wrong terms.
DOC_TYPE_MARKERS = {
    "credit": ("credit agreement", "term loan", "revolving credit"),
    "spa": ("stock purchase agreement", "asset purchase agreement", "merger agreement"),
    "nda": ("non-disclosure agreement", "confidentiality agreement", "mutual nondisclosure"),
}


def detect_doc_type(pages: list[tuple[int, str]], head_pages: int = 3) -> str | None:
    head = " ".join(text for _, text in pages[:head_pages]).lower()
    hits = [t for t, words in DOC_TYPE_MARKERS.items() if any(w in head for w in words)]
    return hits[0] if len(hits) == 1 else None


def legal_step(pages: list[tuple[int, str]], doc_id: str, doc_type: str | None, legal_mod, llm=None) -> Step:
    """Rules-based red flags. With a local model, it also reads the terms the rules did not find (cited, else dropped)."""
    if not doc_type:
        return Step("legal", "skipped", "no document type given (nda, spa or credit)")
    try:
        out = legal_mod.extract(pages, doc_type)
    except ValueError as e:
        return Step("legal", "failed", str(e))
    flags = legal_mod.red_flags(out)
    for f in flags:
        f.setdefault("document_id", doc_id)
    result = {"red_flags": flags, "absent": out.get("absent", [])}
    if llm is None:
        result["model_reader"] = "skipped: no local model configured (LLM_PROVIDER=llamacpp)"
    else:
        from app import legal_reader
        read = legal_reader.read(pages, doc_type, out.get("absent", []), llm, found=out.get("findings", []))
        for f in read["findings"]:
            f["document_id"] = doc_id
        result["model_findings"] = read["findings"]
        result["model_dropped"] = read["dropped"]
        result["model_review"] = read["review"]  # rule and model disagree or the model did not confirm: a person decides
    return Step("legal", "ok", result=result)


def extraction_step(db, tenant: str, doc_id: str, entity: str, data: bytes) -> Step:
    """Verified facts from the filing's own iXBRL tags (no LLM). Failed citations are listed, not stored."""
    from app.ixbrl_facts import extract
    from app.ixbrl_full import read_filing

    _, tags = read_filing(data.decode("utf-8", errors="replace"))
    if not tags:
        return Step("extraction", "skipped", "no inline XBRL tags in this file; use the table or LLM extractors")
    res = extract(db, tenant, doc_id, entity, tags)
    status = "ok" if res["created"] else "failed"
    reason = "" if res["created"] else "no figure passed the citation check"
    return Step("extraction", status, reason, result=res)


COMPS_MIN_PEERS = 5
COMPS_BAND = (Decimal("0.5"), Decimal(2))
COMPS_WIDE_BAND = (Decimal("0.33"), Decimal(3))


def comps_step(revenue: Decimal | None, sic: str | None, exclude: set[str], pages: int, discover) -> Step:
    """SIC peers by size (0.5x to 2x the entity's revenue). When fewer than five are found, the band widens to
    0.33x to 3x for the rest. Each peer keeps its rule, which names the band it was selected in, and its filing link."""
    if revenue is None or not sic:
        return Step("comps", "skipped", "needs the entity's revenue (extraction) and a SIC code")
    found = discover(revenue, sic, exclude, pages=pages, low=COMPS_BAND[0], high=COMPS_BAND[1])
    if len(found) < COMPS_MIN_PEERS:
        seen = exclude | {p.cik for p in found}
        found += discover(revenue, sic, seen, pages=pages, low=COMPS_WIDE_BAND[0], high=COMPS_WIDE_BAND[1],
                          want=10 - len(found))
    return Step("comps", "ok", result={"sic": sic, "target_revenue": str(revenue), "peers": [
        {"cik": p.cik, "name": p.name, "revenue": str(p.revenue), "period": p.period,
         "source_url": p.source_url, "rule": p.rule} for p in found]})


def precedents_step(window: dict | None, build) -> Step:
    """Merger 8-Ks in a date window; each deal's EV and multiples are cited to its filing."""
    if not window:
        return Step("precedents", "skipped", "no date window given (since, until)")
    res = build(window["since"], window["until"], limit=int(window.get("limit", 5)))
    return Step("precedents", "ok", result={"deals": res["deals"], "skipped": res["skipped"],
                                            "stats": res["stats"]})
