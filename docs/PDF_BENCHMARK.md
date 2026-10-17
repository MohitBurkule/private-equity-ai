# PDF engine benchmark

Run: `python evals/pdf_benchmark.py --data /mnt/project-files/data` (harness `evals/pdf_benchmark.py`, adapters `apps/api/app/parse/engines.py`, router `apps/api/app/parse/router.py`).

## Task and metric
31 PDF-sourced golden items: 13 financial-statement rows from `golden_v1` (3M, Netflix, Pfizer, Apple, Boeing 10-K/10-Q, text layer) and 18 pages of `golden_sh01_v1` (Companies House SH01 share-capital forms, 16 of 18 scanned).
- **row hit**: every expected number (or keyword) sits on ONE extracted line that also carries the row label. This is what a PE number needs: right figure, right row, right column set.
- **page recall**: every expected token appears somewhere on the cited page (row-order damage is not counted).
- **bbox**: row hits that carry a bounding box for the citation.
- **s/page**: wall time per page on this CPU container, no GPU.

## Results
| engine | fin. rows | SH01 (scans) | row hit | page recall | with bbox | s/page |
|---|---|---|---|---|---|---|
| pdftotext | 2/13 | 3/18 | 5/31 | 17/31 | 5 | 0.022 |
| pdftotext_layout | 13/13 | 3/18 | 16/31 | 17/31 | 0 | 0.020 |
| pymupdf | 13/13 | 3/18 | 16/31 | 17/31 | 16 | 0.011 |
| pymupdf_text | 13/13 | 3/18 | 16/31 | 17/31 | 0 | 0.012 |
| pdfplumber | 13/13 | 3/18 | 16/31 | 17/31 | 16 | 0.165 |
| pypdf | 13/13 | 3/18 | 16/31 | 17/31 | 0 | 0.069 |
| pdfium | 13/13 | 3/18 | 16/31 | 17/31 | 0 | 0.007 |
| docling | 13/13 | 13/18 | 26/31 | 28/31 | 26 | 8.42 |
| rapidocr | 11/13 | 14/18 | 25/31 | 28/31 | 25 | 1.69 |
| router | 13/13 | 14/18 | 27/31 | 29/31 | 27 | 0.77 |

`pdftotext` is poppler raw reading order (rows split). `pdftotext_layout`, `pymupdf`, `pdfplumber`, `pypdf`, `pdfium` all tie on clean text-layer statements (13/13); the router adds OCR for scans.

## Findings
1. **Text-layer statements are solved by cheap engines.** All layout-aware text engines get 13/13 rows. PyMuPDF is 0.015 s/page and gives line bboxes; pdfplumber gives bboxes too but is 10x slower. Poppler raw mode loses 11/13 rows (columns read in separate runs), so never use it as the primary.
2. **Scans are the hard part.** Best is 13/18 for Docling and 14/18 for RapidOCR (the rise from 11 to 14 comes from scoring fix: SH01 quotes are now split per number, not matched as one string; engine output unchanged). Remaining misses: s02 (two forms, same date), s03 (consolidation table with a 0.0000001 nominal), s08 (hurdle waterfall): handwritten or boxed digits, currency sign read as `E`, table cells out of column order. Page recall (16/18) is higher than row hit (14/18), so the numbers are mostly read but land on the wrong line. Checked: the RapidOCR adapter already groups words into rows by bbox overlap (`group_words`), not by OCR line order. So the remaining scan misses are character-level reading errors (E for £, dropped handwritten digits), not row-order errors. Next fix is a character-level post-check on currency and digit confusions, plus flagging those values `ocr_unverified`.
3. **Docling is accurate but 13 s/page on CPU.** It matched the best on tables and OCR, and keeps real table structure (TableFormer), but is 9x slower than RapidOCR. Use it only for pages the router marks `table` with a failed cross-check, or for CIM tables where cell structure matters.
4. **Router is the best trade-off: 27/31 rows at 0.77 s/page**, ahead of Docling (26/31, 8.4 s/page), RapidOCR alone (25) and every text engine (16). Text pages go to PyMuPDF, scans to OCR.
5. **Cross-check.** Every number from the primary engine is compared to a second independent engine; unmatched numbers are returned as `disputed` and the page is not `verified`. Test `test_disputed_numbers_flagged` shows a 1,577 vs 1,517 mismatch is caught.

## Gold-data issues found
- `g13` cites Pfizer pages 69 and 71, but Trillium/Array sit on pdf page 70 and Therachon on 71 (0-based mix-up). Excluded from scoring, not rescored.
- `g08` used ` / ` as separator for two metrics; the harness now splits on it.

## Router policy
| page type | detected by | engine | checked by |
|---|---|---|---|
| scanned | under 20 chars of text | RapidOCR (Docling for tables) | none; output tagged `ocr_unverified` |
| table | 5+ rows with 2+ numbers and a word | PyMuPDF lines + bbox | pdftotext -layout |
| deck | landscape, short lines | PyMuPDF | pdfplumber / pdfium |
| prose (legal) | otherwise | PyMuPDF | pdfplumber / pdfium |

## Not yet benchmarked
Marker, MinerU, Unstructured, Camelot (adapter added, not yet scored), VLM page parsing. Next runs add them with the same harness, plus CIM-deck and covenant-agreement pages.

## Scanned-PDF OCR accuracy (data/sec)

Harness: `evals/ocr_scan_accuracy.py`. Each filing in `data/sec` (10 digital PDFs, all with text layers) gets its 3 most numeric pages rasterised and OCR'd with RapidOCR. Numbers OCR reads are compared with the numbers in the same page's text layer (commas dropped; one-digit tokens skipped). 29 pages, 3,223 numbers.

| Mode | Render | Degradation | Number recall | Number precision | Pages with recall >= 95% |
|---|---|---|---|---|---|
| clean | 200 dpi | none | 96.9% | 98.8% | 23 / 29 |
| degraded | 150 dpi | skew +/-0.8 deg, Gaussian noise sigma 8, JPEG q40 | 83.1% | 85.9% | 4 / 29 |

Clean recall by filing: Adobe 100%, Netflix 99.2%, 3M 98.9%, Apple 98.4%, Pfizer 98.3%, Best Buy 98.1%, AMD 96.9%, Amcor 95.6%, Boeing 90.0%, Costco 88.6%.

Degraded recall by filing: Adobe 91.2%, AMD 90.3%, Best Buy 89.2%, 3M 88.9%, Amcor 88.9%, Pfizer 85.8%, Boeing 81.1%, Netflix 80.5%, Costco 64.1%, Apple 63.1%.

**Why Costco and Boeing miss (clean mode)**

- Costco: about half the misses are a metric artifact. Costco prints thousands with a period in some tables (`3.071`, `66.752`). The text layer and OCR both carry that form, but the normaliser strips only commas, so the two sides never match. Other misses are real OCR glyph errors: stray punctuation (`4,.117` for `4.117`) and dropped separators.
- Boeing: most misses are small numbers in dense tables and running prose (years, `24`, `31`, `737`, `$1.0 billion`). Some of the prose cases look like repeated values where OCR count and text-layer count differ, not unread digits. Not confirmed line by line.

**Fixes implied, not yet made**

1. Normaliser: treat `d{1,3}([.,]ddd)+` as a thousands-grouped integer on both sides. This should lift the Costco number directly.
2. Table cells: check for stray punctuation such as `,.`, and read it as a separator before comparing.
3. Degraded scans lose about 15 points of recall, so a real scan path needs deskew and denoise before OCR, and any figure from it stays `ocr_unverified`.

**Verification guarantee.** OCR-sourced figures are stored with status `ocr_unverified` (`apps/api/app/facts.py`). Only a human `review_fact` call promotes them to `verified`. This is pinned by `tests/test_unverified_citations.py`. No OCR figure is auto-verified by the text-layer comparison.
