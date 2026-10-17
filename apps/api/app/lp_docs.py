"""LP letters and capital call notices. Pure code: every figure in the text is computed from a caller's input,
and every input carries the source it came from. A figure with no source is refused, never written.

Letter: fund metrics from dated cash flows (fundmetrics.py), portfolio KPIs, and the firm's accepted LP tone
(a cited firm rule). Notice: each LP's share of one capital call or distribution, pro rata to commitments.
Output is a model of numbered paragraphs and a sources list; docx and pptx render from that model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO

from app.fundmetrics import fund_metrics


@dataclass(frozen=True)
class Cite:
    value: str
    source: str  # the filing, document or record the figure was read from
    url: str | None = None


@dataclass(frozen=True)
class Flow:
    on: date
    amount: Decimal  # contributions negative, distributions positive, as an LP sees them
    source: Cite


@dataclass(frozen=True)
class Kpi:
    company: str
    metric: str
    period: str
    value: Cite


@dataclass
class Model:
    title: str
    paragraphs: list[list[tuple[str, int | None]]] = field(default_factory=list)  # (text, source number)
    sources: list[Cite] = field(default_factory=list)

    def cite(self, c: Cite) -> int:
        if c not in self.sources:
            self.sources.append(c)
        return self.sources.index(c) + 1

    def para(self, *parts: tuple[str, Cite | None]) -> None:
        self.paragraphs.append([(t, self.cite(c) if c else None) for t, c in parts])

    def to_dict(self) -> dict:
        return {"title": self.title,
                "paragraphs": [[{"text": t, "source": n} for t, n in p] for p in self.paragraphs],
                "sources": [{"n": i + 1, "value": c.value, "source": c.source, "url": c.url}
                            for i, c in enumerate(self.sources)]}


def _money(v: Decimal) -> str:
    return f"{v.quantize(Decimal('0.01'), ROUND_HALF_UP):,}"


def lp_letter(fund: str, as_of: date, flows: list[Flow], nav: Cite, kpis: list[Kpi],
              tone: Cite | None = None) -> Model:
    """Quarterly LP letter. Without an accepted tone rule the letter says so and uses a neutral style."""
    if not flows:
        raise ValueError("at least one cash flow is needed")
    if any(f.amount == 0 for f in flows):
        raise ValueError("a zero cash flow has no source weight; leave it out")
    nav_value = Decimal(nav.value.replace(",", ""))
    m = fund_metrics([(f.on, f.amount) for f in flows], nav_value, as_of)
    out = Model(f"{fund}: quarterly LP letter, as of {as_of.isoformat()}")
    if tone:
        out.para((f"Firm LP tone rule (accepted): {tone.value}.", tone))
    else:
        out.para(("No accepted LP tone rule; this letter uses a neutral style.", None))
    # every dated flow the totals below are added from, each with its own source
    out.para(*[(f"{f.on.isoformat()} {_money(f.amount)};", f.source) for f in flows])
    out.para(((f"Paid in to date: {_money(m.paid_in)}. Distributed to date: {_money(m.distributed)}. "
               f"Net asset value: {_money(nav_value)} (totals are sums of the flows above)."), nav))
    out.para((f"DPI {m.dpi:.2f}x, RVPI {m.rvpi:.2f}x, TVPI {m.tvpi:.2f}x (derived from the flows and NAV above)."
              if m.dpi is not None else "Multiples are not computable: no capital was paid in.", nav))
    if m.irr is None:
        out.para((f"Net IRR is not reported: {m.irr_note or 'the flows do not give one'}.", None))
    else:
        out.para((f"Net IRR: {m.irr * 100:.1f}% (XIRR, actual/365 days, with NAV as the final flow).", nav))
    if kpis:
        out.para(("Portfolio KPIs (figures as stated in each source):", None))
        for k in kpis:
            out.para((f"{k.company}: {k.metric} {k.value.value} for {k.period}.", k.value))
    return out


def notice_shares(total: Decimal, commitments: dict[str, Decimal]) -> dict[str, Decimal]:
    """Each LP's share of a call or distribution, pro rata to commitments, to the cent. The rounding
    difference (a few pence) goes to the largest commitment so the shares add up exactly."""
    if total <= 0:
        raise ValueError("amount must be positive")
    if not commitments or any(c <= 0 for c in commitments.values()):
        raise ValueError("every LP needs a positive commitment")
    whole = sum(commitments.values())
    shares = {lp: (total * c / whole).quantize(Decimal("0.01"), ROUND_HALF_UP) for lp, c in commitments.items()}
    gap = total - sum(shares.values())
    if gap:
        big = max(commitments, key=commitments.get)
        shares[big] += gap
    return shares


def capital_call_notice(fund: str, amount: Cite, purpose: str, due: date, notice_days: Cite,
                        commitments: dict[str, Cite], kind: str = "capital call",
                        lp: str | None = None) -> Model:
    """One notice per LP (lp=name), or a summary of every LP's share when lp is None. Each commitment is cited."""
    total = Decimal(amount.value.replace(",", ""))
    amounts = {name: Decimal(c.value.replace(",", "")) for name, c in commitments.items()}
    shares = notice_shares(total, amounts)
    if lp is not None and lp not in shares:
        raise ValueError("unknown LP")
    out = Model(f"{fund}: {kind} notice, due {due.isoformat()}")
    out.para(((f"The general partner calls {_money(total)} from limited partners for {purpose}, "
               f"due {due.isoformat()}."), amount))
    out.para((f"Notice period: {notice_days.value} days, as set out in the fund documents.", notice_days))
    if lp is None:
        for name, share in sorted(shares.items()):
            out.para((f"{name}: {_money(share)} (commitment {_money(amounts[name])}).", commitments[name]))
        out.para((f"Shares total {_money(sum(shares.values()))}.", None))
    else:
        out.para(((f"Your share: {_money(shares[lp])}, pro rata to your commitment of {_money(amounts[lp])} "
                   f"out of {_money(sum(amounts.values()))} in total."), commitments[lp]))
    return out


def to_docx(model: Model) -> bytes:
    from docx import Document as Docx

    d = Docx()
    d.add_heading(model.title, level=1)
    for p in model.paragraphs:
        d.add_paragraph("".join(t + (f" [{n}]" if n else "") + " " for t, n in p).strip())
    d.add_heading("Sources", level=2)
    for i, c in enumerate(model.sources, 1):
        d.add_paragraph(f"[{i}] {c.value}: {c.source}" + (f" ({c.url})" if c.url else ""))
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()


def to_pptx(model: Model) -> bytes:
    from pptx import Presentation
    from pptx.util import Pt

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = model.title
    body = prs.slides.add_slide(prs.slide_layouts[1])
    body.shapes.title.text = "Letter"
    tf = body.placeholders[1].text_frame
    tf.word_wrap = True
    first = True
    for p in model.paragraphs:
        text = "".join(t + (f" [{n}]" if n else "") + " " for t, n in p).strip()
        para = tf.paragraphs[0] if first else tf.add_paragraph()
        para.text = text
        para.font.size = Pt(14)
        first = False
    src = prs.slides.add_slide(prs.slide_layouts[1])
    src.shapes.title.text = "Sources"
    stf = src.placeholders[1].text_frame
    stf.word_wrap = True
    for i, c in enumerate(model.sources, 1):
        para = stf.paragraphs[0] if i == 1 else stf.add_paragraph()
        para.text = f"[{i}] {c.value}: {c.source}"
        para.font.size = Pt(12)
    buf = BytesIO()
    prs.save(buf)
    return buf.getvalue()
