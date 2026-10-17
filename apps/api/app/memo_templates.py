"""Named memo templates: which sections a memo carries, and in what order.

Why templates: the IC pack and a one-page snapshot need different sections, and a firm wants its own order. A
template only selects and orders sections the builder already produces from verified, cited facts. It adds no
text of its own, so a template cannot introduce a number that has no source.
"""
from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from app.memo import build_memo_data
from app.models import MemoTemplate

# Section keys, in the order a template lists them. Each key maps to a heading and to the memo field it draws on.
SECTIONS = {
    "financial": "Financial summary",
    "derived": "Derived (computed in code)",
    "risks": "Risks shown by the cited figures",
    "rules": "Firm rules applied (accepted, quoted)",
}

TEMPLATES: dict[str, tuple[str, ...]] = {
    "ic": ("financial", "derived", "risks", "rules"),
    "snapshot": ("derived", "risks"),
}


NAME = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


def validate_sections(sections: list[str]) -> list[str]:
    """A firm template names section keys from SECTIONS only, each once, and at least one."""
    if not sections or len(set(sections)) != len(sections):
        raise ValueError("a template needs at least one section, each listed once")
    bad = [k for k in sections if k not in SECTIONS]
    if bad:
        raise ValueError(f"unknown sections {bad}; choose from {sorted(SECTIONS)}")
    return sections


from app.research import (
    RESEARCH_KEYS,
)

INTRO_MAX = 500
HEADING_MAX = 80


def validate_text(headings: dict[str, str], intro: str, sections: list[str]) -> tuple[dict[str, str], str]:
    """Firm heading text, one line each, no markup. Memo keys must be sections the template carries; research
    note keys (RESEARCH_KEYS) are always allowed, since the research note has its own fixed sections."""
    bad = [k for k in headings if k not in RESEARCH_KEYS and (k not in SECTIONS or k not in sections)]
    if bad:
        raise ValueError(f"headings for sections the template does not carry: {sorted(bad)}")
    clean = {}
    for k, v in headings.items():
        v = v.strip()
        if not v or len(v) > HEADING_MAX or "\n" in v or "#" in v:
            raise ValueError(f"heading for {k} must be 1-{HEADING_MAX} characters, one line, no #")
        clean[k] = v
    intro = intro.strip()
    if len(intro) > INTRO_MAX or "\n" in intro:
        raise ValueError(f"intro must be one line of at most {INTRO_MAX} characters")
    return clean, intro


def firm_text(db: Session, tenant_id: str, template: str) -> tuple[dict[str, str], str]:
    """Firm headings and intro for a template. Built-in templates have none, so they print the defaults."""
    if template in TEMPLATES:
        return {}, ""
    row = db.query(MemoTemplate).filter_by(tenant_id=tenant_id, name=template).one_or_none()
    if row is None:
        return {}, ""
    return json.loads(row.headings or "{}"), row.intro or ""


def resolve(db: Session, tenant_id: str, template: str) -> tuple[str, ...]:
    """Section keys for a built-in or the firm's own template. Anything else is a KeyError."""
    if template in TEMPLATES:
        return TEMPLATES[template]
    row = db.query(MemoTemplate).filter_by(tenant_id=tenant_id, name=template).one_or_none()
    if row is None:
        raise KeyError(template)
    return tuple(json.loads(row.sections))


def list_templates(db: Session, tenant_id: str) -> dict[str, list[str]]:
    out = {k: list(v) for k, v in TEMPLATES.items()}
    for r in db.query(MemoTemplate).filter_by(tenant_id=tenant_id).order_by(MemoTemplate.name).all():
        out[r.name] = json.loads(r.sections)
    return out


def list_text(db: Session, tenant_id: str) -> dict[str, dict]:
    """Firm headings and intro per saved template, for the listing."""
    return {r.name: {"headings": json.loads(r.headings or "{}"), "intro": r.intro or ""}
            for r in db.query(MemoTemplate).filter_by(tenant_id=tenant_id).all()}


def build_memo_sections(db: Session, tenant_id: str, entity: str, template: str,
                        scope: set[str] | None = None) -> str:
    keys = resolve(db, tenant_id, template)
    headings, intro = firm_text(db, tenant_id, template)
    m = build_memo_data(db, tenant_id, entity, scope)
    if m.empty and not m.rules:
        return f"# {entity}\n\nNo verified facts available. Nothing to report.\n"
    items = {
        "financial": [f"- {ln}" for ln in m.lines],
        "derived": [f"- {d}" for d in m.derived],
        "risks": [f"- {r}" for r in m.risks],
        "rules": [f"- {r['label']}: {r['value']} [{r['source']['document_id'][:8]}]" for r in m.rules],
    }
    out = [f"# {entity}: {template} memo (draft, analyst review required)"]
    if intro:
        out += ["", intro]
    for key in keys:
        if items[key]:
            out += ["", f"## {headings.get(key, SECTIONS[key])}", *items[key]]
    return "\n".join([*out, "", "Sources:", *m.notes]) + "\n"
