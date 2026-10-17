"""Financial covenant tests read from credit agreement text. Pure code, no LLM.

A test is taken only from a sentence that says the borrower "shall not permit" a named ratio to be greater or
less than a stated figure, followed by ":1.00" or "to 1.00". Each test returns the section, the quote and the
page it came from. Conditions attached to a test (step-ups, cure rights, fall-away triggers) are returned as
text, never applied, so a reader sees them next to the number. Nothing is inferred from a ratio that is not named.
"""

from __future__ import annotations

import re
from decimal import Decimal

_SENT = re.compile(r"(?<=[.;])\s+(?=[A-Z(\d])")
_TEST = re.compile(
    r"(?:shall not permit|shall not (?:be permitted to )?(?:allow|cause)|will not permit)\s+(?:the\s+)?"
    r"(?P<ratio>(?:Consolidated\s+)?(?:Secured\s+|Total\s+|Senior\s+|Net\s+)*(?:Net\s+)?Leverage Ratio"
    r"|Interest Coverage Ratio|Fixed Charge Coverage Ratio)\s+(?:of Borrower\s+)?(?:to be|be|exceed)?\s*"
    r"(?P<dir>greater than|less than|exceed|be less than)\s+(?P<num>\d+(?:\.\d+)?)\s*:?\s*(?:to\s+)?1\.00",
    re.IGNORECASE,
)
_SECTION = re.compile(
    r"(?<!\w)(\d+\.\d+)\.?\s+(?:Financial Covenants?|Negative Covenants?|[A-Z][A-Za-z ]{3,40})\."
)
_KPI = {
    "secured net leverage ratio": "secured_net_leverage",
    "total net leverage ratio": "total_net_leverage",
    "net leverage ratio": "net_leverage",
    "leverage ratio": "leverage",
    "interest coverage ratio": "interest_coverage",
    "fixed charge coverage ratio": "fixed_charge_coverage",
}
_CONDITIONS = re.compile(
    r"(Fall-Away Event|Financial Covenant Step-Up|Qualifying Acquisition|Cure Right|Specified Equity Contribution)",
    re.IGNORECASE,
)


def extract(pages: list[tuple[int, str]]) -> list[dict]:
    """pages: (number, text). Returns one dict per test with operator (<= or >=), threshold and cite."""
    tests = []
    section = None
    for num, text in pages:
        flat = re.sub(r"\s+", " ", text)
        for sent in _SENT.split(flat):
            s = sent.strip()
            # a bare section number ("7.12.") is split off as its own sentence before the heading text
            head = re.fullmatch(r"(\d+\.\d+)\.", s) or _SECTION.match(s)
            if head:
                section = head.group(1)
            for m in _TEST.finditer(s):
                ratio = re.sub(r"\s+", " ", m.group("ratio")).lower()
                ratio = re.sub(r"^consolidated ", "", ratio)
                kpi = _KPI.get(ratio) or _KPI.get(
                    re.sub(r"^(secured|total) ", "", ratio)
                )
                if kpi is None:
                    continue
                op = (
                    "<="
                    if m.group("dir").lower() in ("greater than", "exceed")
                    else ">="
                )
                tests.append(
                    {
                        "kpi_metric": kpi,
                        "ratio": ratio,
                        "operator": op,
                        "threshold": str(Decimal(m.group("num"))),
                        "section": section,
                        "page": num,
                        "quote": s,
                        "conditions": sorted(
                            {c.group(1) for c in _CONDITIONS.finditer(s)}
                        ),
                    }
                )
    return tests


def check(tests: list[dict], observed: dict[str, dict]) -> list[dict]:
    """Compare parsed tests with observed KPI values. observed: {kpi_metric: {"value", "period", "source"}}.

    Returns one row per test that has an observation: ok or breach, with the test's quote and the observation's
    source. A test with no observation is not guessed; it is listed under `not_tested`."""
    rows, not_tested = [], []
    for t in tests:
        obs = observed.get(t["kpi_metric"])
        if obs is None:
            not_tested.append(
                {"kpi_metric": t["kpi_metric"], "quote": t["quote"], "page": t["page"]}
            )
            continue
        value, limit = Decimal(str(obs["value"])), Decimal(t["threshold"])
        ok = value <= limit if t["operator"] == "<=" else value >= limit
        rows.append(
            {
                "kpi_metric": t["kpi_metric"],
                "status": "ok" if ok else "breach",
                "value": str(value),
                "threshold": t["threshold"],
                "operator": t["operator"],
                "period": obs.get("period"),
                "observation_source": obs.get("source"),
                "covenant_quote": t["quote"],
                "covenant_page": t["page"],
                "section": t["section"],
            }
        )
    return rows + [{"status": "not_tested", **n} for n in not_tested]
