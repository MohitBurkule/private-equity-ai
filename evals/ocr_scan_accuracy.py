"""Scanned-PDF OCR accuracy on the SEC sample set.

Each digital page is rasterised, OCR'd with the repo's RapidOCR path, and the numbers OCR reads are
compared with the numbers in the page's text layer. Two modes:

  clean     200 dpi render, no degradation.
  degraded  150 dpi render, then skew (+/-0.8 deg), Gaussian noise and a JPEG round trip at quality 40,
            to stand in for a real office scan.

Usage: python evals/ocr_scan_accuracy.py --mode clean|degraded|both [--pages 3] [--match NAME] [--dump-misses NAME]
Run from apps/api (needs the pdf and ocr extras). Output is a JSON summary on stdout.
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import re
import sys
from collections import Counter
from io import BytesIO
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.parse import ocr as ocr_mod

SEC = Path("/mnt/project-files/data/sec")
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
MODES = {"clean": {"dpi": 200, "degrade": False}, "degraded": {"dpi": 150, "degrade": True}}


def numbers(text: str) -> list[str]:
    """Numeric tokens, normalised: commas dropped, so 1,234 and 1234 match. One-digit tokens are skipped."""
    out = []
    for tok in NUM.findall(text):
        n = tok.replace(",", "")
        if len(n.replace(".", "")) >= 2:
            out.append(n)
    return out


def pick_pages(doc, count: int) -> list[int]:
    """Table-like pages: the ones with the most numeric tokens."""
    scored = sorted(((len(numbers(doc[i].get_text())), i) for i in range(len(doc))), reverse=True)
    return sorted(i for n, i in scored[:count] if n >= 20)


def degrade(img, seed: int):
    """Skew, noise and JPEG artefacts, seeded per page so runs repeat."""
    import numpy as np
    from PIL import Image

    rng = random.Random(seed)
    img = img.convert("L").rotate(rng.uniform(-0.8, 0.8), resample=Image.BICUBIC, fillcolor=255)
    arr = np.asarray(img).astype(np.float32)
    arr += np.random.default_rng(seed).normal(0, 8, arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=40)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def ocr_image(img) -> str:
    import numpy as np

    if ocr_mod._engine is None:
        from rapidocr_onnxruntime import RapidOCR
        ocr_mod._engine = RapidOCR()
    res, _ = ocr_mod._engine(np.array(img))
    text, _conf = ocr_mod.group_lines(res or [])
    return text


def page_ocr(path: Path, index0: int, mode: str) -> str:
    import pypdfium2 as pdfium

    cfg = MODES[mode]
    img = pdfium.PdfDocument(str(path))[index0].render(scale=cfg["dpi"] / 72).to_pil()
    if cfg["degrade"]:
        img = degrade(img, seed=index0)
    return ocr_image(img)


def run(mode: str, pages_per_doc: int, dump: str | None, match: str = "") -> dict:
    per_doc = {}
    tot = {"text": 0, "ocr": 0, "hit": 0, "pages": 0, "pages_ok": 0}
    for f in sorted(glob.glob(str(SEC / "*.pdf"))):
        name = Path(f).name
        if match not in name:
            continue
        doc = pymupdf.open(f)
        d = {"text": 0, "ocr": 0, "hit": 0}
        for i in pick_pages(doc, pages_per_doc):
            text_nums = Counter(numbers(doc[i].get_text()))
            ocr_text = page_ocr(Path(f), i, mode)
            ocr_nums = Counter(numbers(ocr_text))
            hit = sum((text_nums & ocr_nums).values())
            n_text = sum(text_nums.values())
            d["text"] += n_text
            d["ocr"] += sum(ocr_nums.values())
            d["hit"] += hit
            tot["pages"] += 1
            tot["pages_ok"] += int(bool(n_text) and hit / n_text >= 0.95)
            if dump and dump in name:
                for tok in text_nums - ocr_nums:
                    print(f"MISS {name} p{i + 1} {tok!r}", file=sys.stderr)
                    for line in ocr_text.splitlines():
                        if tok[-2:] in line.replace(",", ""):
                            print(f"    near: {line.strip()[:140]}", file=sys.stderr)
                            break
        per_doc[name] = {
            "recall": round(d["hit"] / max(d["text"], 1), 3),
            "precision": round(d["hit"] / max(d["ocr"], 1), 3),
            "text_numbers": d["text"],
        }
        for k, v in zip(("text", "ocr", "hit"), (d["text"], d["ocr"], d["hit"])):
            tot[k] += v
    return {
        "mode": mode,
        "dpi": MODES[mode]["dpi"],
        "degraded": MODES[mode]["degrade"],
        "recall": round(tot["hit"] / max(tot["text"], 1), 3),
        "precision": round(tot["hit"] / max(tot["ocr"], 1), 3),
        "text_numbers": tot["text"],
        "pages": tot["pages"],
        "pages_recall_ge_95": tot["pages_ok"],
        "per_doc": per_doc,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["clean", "degraded", "both"], default="both")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--dump-misses", default=None, help="substring of a filename to print missed numbers for")
    ap.add_argument("--match", default="", help="only run filenames containing this substring")
    args = ap.parse_args()
    modes = list(MODES) if args.mode == "both" else [args.mode]
    print(json.dumps([run(m, args.pages, args.dump_misses, args.match) for m in modes], indent=2))


if __name__ == "__main__":
    main()
