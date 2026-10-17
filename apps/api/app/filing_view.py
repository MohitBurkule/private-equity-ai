"""The filing page as filed, as HTML, with the tagged figure highlighted and scrollable.

A filing's pages are marked by page-break styles, so a page is the markup between two breaks.
The figure is found by its iXBRL tag, which keeps the highlight on the number itself rather than on
a text match that could land on the same figure in another table. Scripts are removed; the filer's
own styles are kept so the page looks as it was filed.
"""
from __future__ import annotations

import re

from app.ixbrl_full import Tagged

_BREAK = re.compile(r"page-break-(?:after|before)\s*:\s*always", re.IGNORECASE)
_STYLE = re.compile(r"<style\b.*?</style\s*>", re.DOTALL | re.IGNORECASE)
_SCRIPT = re.compile(r"<script\b.*?</script\s*>", re.DOTALL | re.IGNORECASE)
_HIGHLIGHT_CSS = ".pe-hl{background:#fde047;outline:2px solid #facc15;scroll-margin:40vh}"


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def _pick(tags: list[Tagged], page: int, quote: str) -> tuple[Tagged | None, bool]:
    """The figure whose table row is the quote, else the page's first figure (not highlighted as a quote)."""
    on_page = [t for t in tags if t.page == page and t.pos >= 0]
    q = _norm(quote)
    for t in on_page:
        if q and t.row and (_norm(t.row) == q or q in _norm(t.row)):
            return t, True
    return (on_page[0] if on_page else None), False


def _page_bounds(html: str, pos: int) -> tuple[int, int]:
    """Start and end of the page holding `pos`. A break-after element closes the page it sits in, so the
    page runs to the end of that element; a break-before element opens the next page at its own start."""
    start, end = 0, len(html)
    for m in _BREAK.finditer(html):
        tag_start = html.rfind("<", 0, m.start())
        after = "after" in m.group(0).lower()
        if after:
            close = html.find("</div", m.end())
            close_end = html.find(">", close) + 1 if close >= 0 else m.end()
        if tag_start < pos:
            start = close_end if after else tag_start
        elif end == len(html):
            end = close_end if after else tag_start
            break
    return start, end


def _locate(html: str, tags: list[Tagged], page: int, quote: str, anchor: str | None,
            offset: int | None) -> tuple[int, bool] | None:
    """Where to highlight: a character offset, an element id, or the figure matching the quote on the page."""
    if offset is not None:
        return (offset, True) if 0 <= offset < len(html) else None
    if anchor:
        m = re.search(r'<[^>]*\bid="' + re.escape(anchor) + '"', html)
        return (m.start(), True) if m else None
    target, found = _pick(tags, page, quote)
    return (target.pos, found) if target else None


def _mark(body: str, rel: int) -> str:
    """Give the element starting at `rel` the highlight class on its own start tag. Wrapping it in a span
    would put a span between table rows or cells, which browsers move out of the table."""
    m = re.match(r"<([A-Za-z][\w:.-]*)", body[rel:])
    if not m:
        return body
    name_end = rel + m.end()
    return f'{body[:name_end]} class="pe-hl"{body[name_end:]}'


def filing_page_html(html: str, tags: list[Tagged], page: int, quote: str, anchor: str | None = None,
                     offset: int | None = None) -> tuple[str, bool] | None:
    """(document, highlighted) for the page holding the target, or None when there is no target.
    The target is a character offset or element id when given (a citation that names an anchor),
    else the tagged figure whose row is the quote."""
    located = _locate(html, tags, page, quote, anchor, offset)
    if located is None:
        return None
    pos, found = located
    start, end = _page_bounds(html, pos)
    body = _SCRIPT.sub("", html[start:end])
    rel = pos - start
    # A figure picked only as the page's first figure is not the quote, so it is not marked.
    if found or anchor or offset is not None:
        body = _mark(body, rel)
    styles = "\n".join(_STYLE.findall(html))
    doc = (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"{styles}<style>{_HIGHLIGHT_CSS}</style></head><body>{body}</body></html>"
    )
    return doc, found
