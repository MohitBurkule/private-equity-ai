"""Sourcing and add-on screening: a target universe seeded from SEC and Companies House, filtered by strategy.

Nothing is guessed: a company with no stated revenue keeps revenue None, and a screen reports it as
`unknown` for the revenue criterion instead of passing or failing it. SEC revenue is the latest full-year
us-gaap revenue figure from a 10-K with a filing link; Companies House bulk data carries no financials.
"""
from __future__ import annotations

import re
from collections.abc import Callable
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


# Approximate geographic centre of each US state, used only to place SEC targets on the map.
# It is a placement aid, not a location claim: the list shows the real state code beside every dot.
US_STATE_CENTROIDS = {
    "AL": (32.8, -86.8), "AK": (64.0, -152.0), "AZ": (34.3, -111.7), "AR": (34.9, -92.4), "CA": (37.2, -119.5),
    "CO": (39.0, -105.5), "CT": (41.6, -72.7), "DE": (39.0, -75.5), "FL": (28.6, -82.4), "GA": (32.7, -83.4),
    "HI": (20.9, -157.5), "ID": (44.4, -114.6), "IL": (40.0, -89.2), "IN": (39.9, -86.3), "IA": (42.1, -93.5),
    "KS": (38.5, -98.4), "KY": (37.5, -85.3), "LA": (31.1, -92.0), "ME": (45.4, -69.2), "MD": (39.0, -76.8),
    "MA": (42.3, -71.8), "MI": (44.3, -85.4), "MN": (46.3, -94.3), "MS": (32.7, -89.7), "MO": (38.4, -92.5),
    "MT": (47.0, -109.6), "NE": (41.5, -99.8), "NV": (39.3, -116.6), "NH": (43.7, -71.6), "NJ": (40.2, -74.7),
    "NM": (34.4, -106.1), "NY": (42.9, -75.5), "NC": (35.5, -79.4), "ND": (47.4, -100.5), "OH": (40.3, -82.8),
    "OK": (35.6, -97.5), "OR": (43.9, -120.6), "PA": (40.9, -77.8), "RI": (41.7, -71.6), "SC": (33.9, -80.9),
    "SD": (44.4, -100.2), "TN": (35.9, -86.4), "TX": (31.5, -99.3), "UT": (39.3, -111.7), "VT": (44.1, -72.7),
    "VA": (37.5, -78.9), "WA": (47.4, -120.5), "WV": (38.6, -80.6), "WI": (44.6, -89.9), "WY": (43.0, -107.6),
    "DC": (38.9, -77.0),
}


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
    if not biz.get("isForeignLocation") and biz.get("stateOrCountry") in US_STATE_CENTROIDS:
        t.lat, t.lng = (Decimal(str(v)) for v in US_STATE_CENTROIDS[biz["stateOrCountry"]])
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


def live_sec_fetch(cik: str) -> tuple[dict, dict]:
    """Live SEC submissions and company facts for one CIK, in the shape sec_target expects."""
    import json

    from app.edgar import fetch_companyfacts
    from app.secfeed import default_fetch
    subs = json.loads(default_fetch(f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"))
    return subs, fetch_companyfacts(cik)


def refresh_universe(db: Session, tenant: str, fetch_sec: Callable, fetch_ch: Callable,
                     limit: int = 200) -> dict:
    """Re-pull each stored SEC or Companies House target from its source and update the row in place.
    A source that fails, or a company that is dissolved or unknown, leaves its row as it was and is counted."""
    rows = (db.query(Target).filter(Target.tenant_id == tenant, Target.source.in_(["sec", "companies_house"]))
            .order_by(Target.id).limit(limit).all())
    refreshed, failed, dissolved = 0, 0, 0
    for r in rows:
        try:
            if r.source == "sec":
                submissions, facts = fetch_sec(r.source_ref)
                it = sec_target(submissions, facts)
            else:
                rec = fetch_ch(r.source_ref)
                if rec is None:
                    failed += 1
                    continue
                if rec.status and rec.status.lower() != "active":
                    dissolved += 1
                    continue  # dissolved companies are not targets; the row is kept, never silently refreshed
                sic = rec.sic[0] if rec.sic else None
                it = TargetIn(rec.name or r.name, "companies_house", rec.number,
                              f"https://find-and-update.company-information.service.gov.uk/company/{rec.number}",
                              uk_sector(sic), sic, "United Kingdom", r.region)
        except (KeyError, ValueError, OSError, RuntimeError):  # one bad source must not stop the rest
            failed += 1
            continue
        upsert(db, tenant, [it])
        refreshed += 1
    return {"checked": len(rows), "refreshed": refreshed, "failed": failed, "dissolved": dissolved}


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
            "revenue_period": t.revenue_period, "revenue_url": t.revenue_url, "status": t.status,
            "website": t.website, "web_title": t.web_title, "web_description": t.web_description,
            "web_site_name": t.web_site_name, "web_checked_at": t.web_checked_at}


def benchmark(db: Session, tenant: str, sector: str | None, target: Target | None = None) -> dict:
    """Revenue benchmark for a sector across this tenant's targets. Only targets with a stated revenue count;
    the rest are reported as excluded, never assumed. Percentile places one target inside the peer group."""
    from app.comps import stats

    q = db.query(Target).filter(Target.tenant_id == tenant)
    if sector:
        q = q.filter(Target.sector.ilike(f"%{sector}%"))
    rows = [r for r in q.all() if target is None or r.id != target.id]  # the target is not its own peer
    known = [r.revenue for r in rows if r.revenue is not None]
    st = stats(known)
    # every peer behind the median, with the link to the figure it came from
    inputs = [{"id": r.id, "name": r.name, "revenue": str(r.revenue), "revenue_period": r.revenue_period,
               "revenue_url": r.revenue_url, "source_url": r.source_url}
              for r in rows if r.revenue is not None]
    out = {"sector": sector, "peers": st.n, "excluded_no_revenue": len(rows) - st.n, "inputs": inputs,
           "median": None if st.median is None else str(st.median),
           "q1": None if st.q1 is None else str(st.q1), "q3": None if st.q3 is None else str(st.q3),
           "min": None if st.low is None else str(st.low), "max": None if st.high is None else str(st.high)}
    if target is not None and target.revenue is not None and known:
        below = sum(1 for v in known if v < target.revenue)  # peers strictly below the target
        out["target"] = {"id": target.id, "name": target.name, "revenue": str(target.revenue),
                         "percentile": round(100 * below / len(known))}
    return out
