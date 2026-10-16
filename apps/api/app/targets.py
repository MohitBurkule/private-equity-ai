"""Sourcing and add-on screening: a target universe seeded from SEC and Companies House, filtered by strategy.

Nothing is guessed: a company with no stated revenue keeps revenue None, and a screen reports it as
`unknown` for the revenue criterion instead of passing or failing it. SEC revenue is the latest full-year
us-gaap revenue figure from a 10-K with a filing link; Companies House bulk data carries no financials.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.chbulk import iter_basic_company_csv
from app.models import Target

_REV_TAGS = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
             "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet")
# UK SIC 2007 sections by 2-digit division; sector label keeps the exact code so nothing is hidden
_SECTIONS = [(1, 3, "Agriculture"), (5, 9, "Mining"), (10, 33, "Manufacturing"), (35, 35, "Utilities"),
             (36, 39, "Water and waste"), (41, 43, "Construction"), (45, 47, "Wholesale and retail"),
             (49, 53, "Transport and storage"), (55, 56, "Hospitality"), (58, 63, "Information and communication"),
             (64, 66, "Financial services"), (68, 68, "Real estate"), (69, 75, "Professional services"),
             (77, 82, "Administrative services"), (84, 84, "Public administration"), (85, 85, "Education"),
             (86, 88, "Health and social care"), (90, 93, "Arts and recreation"), (94, 96, "Other services")]


def uk_sector(sic: str | None) -> str | None:
    if not sic or not sic[:2].isdigit():
        return None
    div = int(sic[:2])
    name = next((n for lo, hi, n in _SECTIONS if lo <= div <= hi), None)
    return f"{name} (SIC {sic})" if name else f"SIC {sic}"


@dataclass
class TargetIn:
    name: str
    source: str
    source_ref: str
    source_url: str | None = None
    sector: str | None = None
    sic: str | None = None
    country: str | None = None
    region: str | None = None
    lat: Decimal | None = None
    lng: Decimal | None = None
    revenue: Decimal | None = None
    currency: str | None = None
    revenue_period: str | None = None
    revenue_url: str | None = None


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def sec_target(submissions: dict, facts: dict | None) -> TargetIn:
    cik = str(int(submissions["cik"]))
    biz = (submissions.get("addresses") or {}).get("business") or {}
    t = TargetIn(submissions["name"], "sec", cik.zfill(10), f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
                 submissions.get("sicDescription") or None, submissions.get("sic") or None,
                 "United States" if not biz.get("isForeignLocation") else (biz.get("stateOrCountryDescription") or None),
                 biz.get("stateOrCountry") if not biz.get("isForeignLocation") else None)
    best = None
    for tag in _REV_TAGS:
        for e in ((facts or {}).get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD", [])):
            if e.get("form") != "10-K" or e.get("fp") != "FY" or not e.get("start") or not e.get("end"):
                continue
            if not 350 <= _days(e["start"], e["end"]) <= 380:
                continue
            if best is None or (e["end"], e.get("filed", "")) > (best[0]["end"], best[0].get("filed", "")):
                best = (e, tag)
        if best:
            break  # first tag with data wins; tags are not mixed
    if best:
        e, _ = best
        t.revenue, t.currency, t.revenue_period = Decimal(str(e["val"])), "USD", f"FY{e['end'][:4]} (to {e['end']})"
        t.revenue_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{e['accn'].replace('-', '')}/"
    return t


def ch_targets(csv_text: str) -> list[TargetIn]:
    out = []
    for r in iter_basic_company_csv(csv_text):
        if r.status and r.status.lower() != "active" or not r.name:
            continue  # dissolved companies are not targets
        sic = r.sic_codes[0] if r.sic_codes else None
        out.append(TargetIn(r.name, "companies_house", r.number,
                            f"https://find-and-update.company-information.service.gov.uk/company/{r.number}",
                            uk_sector(sic), sic,
                            "United Kingdom", re.sub(r"\s+\d\w\w$", "", r.postcode or "") or None))
    return out


def upsert(db: Session, tenant: str, items: list[TargetIn]) -> tuple[int, int]:
    new = upd = 0
    for it in items:
        row = db.query(Target).filter_by(tenant_id=tenant, source=it.source, source_ref=it.source_ref).one_or_none()
        if row is None:
            db.add(Target(tenant_id=tenant, **it.__dict__))
            new += 1
        else:
            for k, v in it.__dict__.items():
                if v is not None:
                    setattr(row, k, v)  # a missing field never erases a known one
            upd += 1
    db.commit()
    return new, upd


@dataclass
class Criteria:
    sectors: list[str] = field(default_factory=list)  # substring match on sector, case-insensitive
    countries: list[str] = field(default_factory=list)
    min_revenue: Decimal | None = None
    max_revenue: Decimal | None = None


def evaluate(t: Target, c: Criteria) -> dict:
    res: dict[str, str] = {}
    if c.sectors:
        res["sector"] = ("unknown" if not t.sector else
                         "pass" if any(s.lower() in t.sector.lower() for s in c.sectors) else "fail")
    if c.countries:
        res["country"] = ("unknown" if not t.country else
                          "pass" if t.country.lower() in {x.lower() for x in c.countries} else "fail")
    if c.min_revenue is not None or c.max_revenue is not None:
        if t.revenue is None:
            res["revenue"] = "unknown"
        else:
            ok = ((c.min_revenue is None or t.revenue >= c.min_revenue)
                  and (c.max_revenue is None or t.revenue <= c.max_revenue))
            res["revenue"] = "pass" if ok else "fail"
    verdict = "fail" if "fail" in res.values() else "review" if "unknown" in res.values() else "match"
    return {"verdict": verdict, "criteria": res}


def to_dict(t: Target) -> dict:
    return {"id": t.id, "name": t.name, "source": t.source, "source_ref": t.source_ref, "source_url": t.source_url,
            "sector": t.sector, "sic": t.sic, "country": t.country, "region": t.region,
            "lat": None if t.lat is None else str(t.lat), "lng": None if t.lng is None else str(t.lng),
            "revenue": None if t.revenue is None else str(t.revenue), "currency": t.currency,
            "revenue_period": t.revenue_period, "revenue_url": t.revenue_url, "status": t.status}
