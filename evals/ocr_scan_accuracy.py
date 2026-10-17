"""Scanned-PDF OCR accuracy on the SEC sample set.

Each digital page is rasterised, OCR'd, and the numbers OCR reads are compared with the numbers in the
page's text layer. Modes:

  clean          200 dpi render, no degradation.
  degraded       150 dpi render, then skew (+/-0.8 deg), Gaussian noise and a JPEG round trip (quality 40).

Engines: rapid (RapidOCR), tesseract (CLI), vote (a number counts only when both engines read it; numbers
only one engine reads are "disputed" and go to the review queue).

A token like 3.071 is ambiguous (decimal or thousands). Unless the page has comma-thousands numbers,
period-thousands tokens are counted as ambiguous and reported separately, never guessed.

Usage: python evals/ocr_scan_accuracy.py --mode clean|degraded|all --engine rapid|tesseract|vote
       [--pages 3] [--match NAME] [--dump-misses NAME]
Run from apps/api (pdf and ocr extras; tesseract on PATH for tesseract and vote). Output is JSON on stdout.
"""

from __future__ import annotations

import argparse
import glob
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from io import BytesIO
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.parse import ocr as ocr_mod

SEC = Path("/mnt/project-files/data/sec")
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
PERIOD_THOUSANDS = re.compile(r"^\d{1,3}\.\d{3}$")
COMMA_THOUSANDS = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
MODES = {
    "clean": {"dpi": 200, "degrade": False},
    "degraded": {"dpi": 150, "degrade": True},
}


def raw_numbers(text: str) -> list[str]:
    return [
        t for t in NUM.findall(text) if len(t.replace(",", "").replace(".", "")) >= 2
    ]


def numbers(text: str) -> list[str]:
    """Numeric tokens with commas dropped (1,234 matches 1234). One-digit tokens are skipped."""
    return [t.replace(",", "") for t in raw_numbers(text)]


def page_uses_comma_thousands(text: str) -> bool:
    return sum(1 for t in raw_numbers(text) if COMMA_THOUSANDS.match(t)) >= 2


def pick_pages(doc, count: int) -> list[int]:
    """Table-like pages: the ones with the most numeric tokens."""
    scored = sorted(
        ((len(numbers(doc[i].get_text())), i) for i in range(len(doc))), reverse=True
    )
    return sorted(i for n, i in scored[:count] if n >= 20)


def degrade(img, seed: int):
    """Skew, noise and JPEG artefacts, seeded per page so runs repeat."""
    import numpy as np
    from PIL import Image

    rng = random.Random(seed)
    img = img.convert("L").rotate(
        rng.uniform(-0.8, 0.8), resample=Image.BICUBIC, fillcolor=255
    )
    arr = np.asarray(img).astype(np.float32)
    arr += np.random.default_rng(seed).normal(0, 8, arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=40)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def ocr_rapid(img) -> str:
    import numpy as np

    if ocr_mod._engine is None:
        from rapidocr_onnxruntime import RapidOCR

        ocr_mod._engine = RapidOCR()
    res, _ = ocr_mod._engine(np.array(img))
    text, _conf = ocr_mod.group_lines(res or [])
    return text


def ocr_tesseract(img) -> str:
    if shutil.which("tesseract") is None:
        raise RuntimeError("tesseract not on PATH")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "page.png"
        img.save(path)
        out = subprocess.run(
            ["tesseract", str(path), "-", "--psm", "6"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    return out.stdout


def page_image(path: Path, index0: int, mode: str):
    import pypdfium2 as pdfium

    cfg = MODES[mode]
    img = pdfium.PdfDocument(str(path))[index0].render(scale=cfg["dpi"] / 72).to_pil()
    if cfg["degrade"]:
        img = degrade(img, seed=index0)
    return img


def run(
    mode: str, engine: str, pages_per_doc: int, dump: str | None, match: str
) -> dict:
    per_doc = {}
    tot: Counter = Counter()
    for f in sorted(glob.glob(str(SEC / "*.pdf"))):
        name = Path(f).name
        if match not in name:
            continue
        doc = pymupdf.open(f)
        d: Counter = Counter()
        for i in pick_pages(doc, pages_per_doc):
            page_text = doc[i].get_text()
            text_nums = Counter(numbers(page_text))
            ambiguous = set()
            if not page_uses_comma_thousands(page_text):
                ambiguous = {t for t in text_nums if PERIOD_THOUSANDS.match(t)}
            unamb_nums = Counter(
                {k: v for k, v in text_nums.items() if k not in ambiguous}
            )
            img = page_image(Path(f), i, mode)
            if engine == "rapid":
                ocr_nums = Counter(numbers(ocr_rapid(img)))
            elif engine == "tesseract":
                ocr_nums = Counter(numbers(ocr_tesseract(img)))
            else:  # vote: a value counts only where both engines read it
                a = Counter(numbers(ocr_rapid(img)))
                b = Counter(numbers(ocr_tesseract(img)))
                ocr_nums = a & b
                d["disputed"] += sum(((a | b) - ocr_nums).values())
            d["text"] += sum(text_nums.values())
            d["text_unamb"] += sum(unamb_nums.values())
            d["ambiguous"] += sum(text_nums[t] for t in ambiguous)
            d["ocr"] += sum(ocr_nums.values())
            d["hit"] += sum((text_nums & ocr_nums).values())
            d["hit_unamb"] += sum((unamb_nums & ocr_nums).values())
            d["pages"] += 1
            if dump and dump in name:
                for tok in text_nums - ocr_nums:
                    print(f"MISS {name} p{i + 1} {tok!r}", file=sys.stderr)
        tot.update(d)
        per_doc[name] = {
            "recall": round(d["hit"] / max(d["text"], 1), 3),
            "precision": round(d["hit"] / max(d["ocr"], 1), 3),
            "text_numbers": d["text"],
        }
    return {
        "mode": mode,
        "engine": engine,
        "recall": round(tot["hit"] / max(tot["text"], 1), 3),
        "precision": round(tot["hit"] / max(tot["ocr"], 1), 3),
        "recall_unambiguous": round(tot["hit_unamb"] / max(tot["text_unamb"], 1), 3),
        "ambiguous_period_thousands": tot["ambiguous"],
        "disputed_for_review": tot["disputed"],
        "text_numbers": tot["text"],
        "pages": tot["pages"],
        "per_doc": per_doc,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=[*MODES, "all"], default="clean")
    ap.add_argument("--engine", choices=["rapid", "tesseract", "vote"], default="rapid")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument(
        "--match", default="", help="only run filenames containing this substring"
    )
    ap.add_argument(
        "--dump-misses",
        default=None,
        help="substring of a filename to print missed numbers for",
    )
    args = ap.parse_args()
    modes = list(MODES) if args.mode == "all" else [args.mode]
    print(
        json.dumps(
            [
                run(m, args.engine, args.pages, args.dump_misses, args.match)
                for m in modes
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
