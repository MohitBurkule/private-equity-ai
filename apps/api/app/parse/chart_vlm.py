"""Chart value extraction, option A: a small vision-language model reads each chart picture. Off unless
CHART_VLM=1 and CHART_VLM_MODEL / CHART_VLM_MMPROJ point at GGUF files (Qwen2.5-VL-3B via llama-cpp-python).

The model's numbers are trusted only when they match a label OCR read on the same chart, or a number in the
page's text layer. A match gives the bbox of that label (or none for a page-text match). Anything else is
returned unverified with no bbox, so a reader can see it came from the model alone.
"""
from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from app.parse.charts import (
    ChartValue,
    chart_regions,
    parse_number,
    read_region,
    render_region,
)

PROMPT = (
    "List every number printed on this chart, including axis ticks and value labels. "
    "Reply with only a JSON array of strings, each exactly as printed. Do not estimate values."
)
PAGE_NUM = re.compile(r"\(?-?\$?£?€?\d[\d,]*(?:\.\d+)?%?\)?")
QUOTED = re.compile(r'"([^"\n]{1,40})"')

_llm = None


@dataclass(frozen=True)
class VlmValue:
    page: int
    text: str
    value: float
    verified: bool
    bbox: tuple[float, float, float, float] | None  # PDF points, top-left origin; None when unverified
    source: str | None  # "ocr" | "page_text" | None when unverified


def vlm_enabled() -> bool:
    return os.environ.get("CHART_VLM") == "1" and bool(os.environ.get("CHART_VLM_MODEL"))


def _load():
    global _llm
    if _llm is None:
        from llama_cpp import Llama
        from llama_cpp.llama_chat_format import Qwen25VLChatHandler
        handler = Qwen25VLChatHandler(clip_model_path=os.environ["CHART_VLM_MMPROJ"], verbose=False)
        _llm = Llama(model_path=os.environ["CHART_VLM_MODEL"], chat_handler=handler,
                     n_ctx=2048, n_threads=os.cpu_count(), verbose=False)
    return _llm


MAX_SIDE = 672  # CPU prefill cost grows with image tokens; chart labels stay legible at this size


def shrink(png: bytes) -> bytes:
    from PIL import Image
    img = Image.open(BytesIO(png))
    if max(img.size) <= MAX_SIDE:
        return png
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def ask_vlm(png: bytes) -> list[str]:
    """Labels the model reads off one chart image. Malformed output gives an empty list, not an error."""
    png = shrink(png)
    uri = "data:image/png;base64," + base64.b64encode(png).decode()
    out = _load().create_chat_completion(
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": uri}},
            {"type": "text", "text": PROMPT},
        ]}],
        temperature=0,
        max_tokens=200,
    )
    return parse_labels(out["choices"][0]["message"]["content"] or "")


def parse_labels(text: str) -> list[str]:
    """Quoted strings in the model's reply, in order, without repeats. Works on a reply cut off mid-array,
    which the model produces when it repeats a label until the token cap."""
    return list(dict.fromkeys(QUOTED.findall(text)))


def page_text_numbers(path: Path, page: int) -> set[float]:
    import pypdfium2 as pdfium
    text = pdfium.PdfDocument(str(path))[page - 1].get_textpage().get_text_range()
    return {v for m in PAGE_NUM.findall(text) if (v := parse_number(m)) is not None}


def verify(labels: list[str], ocr: list[ChartValue], text_numbers: set[float], page: int) -> list[VlmValue]:
    """Keep a model label as verified only if its value matches OCR on the chart or the page text layer."""
    out: list[VlmValue] = []
    seen: set[tuple[str, float]] = set()
    for label in labels:
        value = parse_number(label)
        if value is None or (label, value) in seen:
            continue
        seen.add((label, value))
        hit = next((o for o in ocr if o.value == value), None)
        if hit is not None:
            out.append(VlmValue(page, label, value, True, hit.bbox, "ocr"))
        elif value in text_numbers:
            out.append(VlmValue(page, label, value, True, None, "page_text"))
        else:
            out.append(VlmValue(page, label, value, False, None, None))
    return out


def extract_vlm_values(path: Path, page: int) -> list[VlmValue]:
    if not vlm_enabled():
        return []
    text_numbers = page_text_numbers(path, page)
    vals: list[VlmValue] = []
    for box in chart_regions(path, page):
        buf = BytesIO()
        render_region(path, page, box).save(buf, format="PNG")
        ocr = read_region(path, page, box)
        labels = ask_vlm(buf.getvalue())
        if not labels:
            # The model said nothing usable: fall back to the labels OCR read on the chart. They still cite
            # their bbox and still land as ocr_unverified in the review queue.
            labels = [o.text for o in ocr]
        vals.extend(verify(labels, ocr, text_numbers, page))
    return vals
