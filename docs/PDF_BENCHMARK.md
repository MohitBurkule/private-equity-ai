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
| degraded, vote | 150 dpi | as above; a number counts only if RapidOCR and Tesseract both read it | 75.2% | 98.4% | not measured |

Vote: 1,381 numbers that only one engine read go to the review queue as `disputed` and are not counted as recall. Precision rises from 85.9% to 98.4%; recall falls by about 8 points. Vote is the chosen degraded path because a wrong figure costs more than a missed one, and missed figures stay visible in review.

Preprocessing tried and dropped: deskew (minAreaRect), denoise (non-local means), Otsu binarise, 2x upscale on the degraded render. Degraded recall fell to 78.1% and precision to 81.0%, so it was removed from the harness.

Ambiguous tokens: a token like `3.071` could be a decimal or a thousands separator. Unless the page has comma-thousands numbers, these are counted apart from scored recall (9 in the degraded run) and never guessed.

Clean recall by filing: Adobe 100%, Netflix 99.2%, 3M 98.9%, Apple 98.4%, Pfizer 98.3%, Best Buy 98.1%, AMD 96.9%, Amcor 95.6%, Boeing 90.0%, Costco 88.6%.

Degraded recall by filing: Adobe 91.2%, AMD 90.3%, Best Buy 89.2%, 3M 88.9%, Amcor 88.9%, Pfizer 85.8%, Boeing 81.1%, Netflix 80.5%, Costco 64.1%, Apple 63.1%.

**Why Costco and Boeing miss (clean mode)**

- Costco: about half the misses are a metric artifact. Costco prints thousands with a period in some tables (`3.071`, `66.752`). The text layer and OCR both carry that form, but the normaliser strips only commas, so the two sides never match. Other misses are real OCR glyph errors: stray punctuation (`4,.117` for `4.117`) and dropped separators.
- Boeing: most misses are small numbers in dense tables and running prose (years, `24`, `31`, `737`, `$1.0 billion`). Some of the prose cases look like repeated values where OCR count and text-layer count differ, not unread digits. Not confirmed line by line.

**Fixes implied, not yet made**

1. Normaliser: `d.ddd` tokens are ambiguous. They are flagged for review unless the page's other numbers use comma thousands, and are never guessed as thousands groups.
2. Table cells: check for stray punctuation such as `,.`, and read it as a separator before comparing. Not done yet.
3. Degraded scans: vote between two engines, with disagreements sent to review. Preprocessing did not help and was dropped. Any figure from a scan stays `ocr_unverified`.

**Verification guarantee.** OCR-sourced figures are stored with status `ocr_unverified` (`apps/api/app/facts.py`). Only a human `review_fact` call promotes them to `verified`. This is pinned by `tests/test_unverified_citations.py`. No OCR figure is auto-verified by the text-layer comparison.

## Table-row pairing (golden PDF items)

Harness: `evals/pdf_benchmark.py`, 31 golden PDF items (13 from `golden_v1`, 18 from `golden_sh01_v1`). `row` means every expected number and the row label sit on one line. Docling 2.x table model weights are reachable from this environment (HF HTTP 307), so Docling was run as a candidate.

| Engine | Page hit | Row hit | Bbox on row | s/page |
|---|---|---|---|---|
| pypdf | 17/31 | 16/31 | 0 | 0.19 |
| pymupdf_text | 17/31 | 16/31 | 0 | 0.13 |
| pdfplumber | 17/31 | 16/31 | 16 | 0.19 |
| router (current extractor) | 29/31 | 27/31 | 27 | 1.13 |
| docling | 28/31 | 26/31 | 26 | 10.53 |

The `golden_v1` subset scores 13/13 for every engine, so the gap is in the sh01 forms (router 14/18 rows, Docling 13/18).

Decision: keep the router. Docling does not win on row pairing and costs about 9x the time per page. Not adopted. Docling stays available as an engine in `apps/api/app/parse/engines.py`.

## SH01 router misses (golden_sh01)

Harness fix: a golden quote joins two cells with ` ... `, which sit on separate lines of the same form. The harness now scores each side as its own part, so `s02` p1 `Number allotted 53819 ... Amount paid: 7.41` no longer needs both numbers on one line. Router row integrity moves from 27/31 to 28/31.

Left as misses, not fixed:
- `s02` p1 (monzo_20250303): `Totals 11,234,414` is not in the router's OCR text for that page. OCR limit on a scanned form.
- `s03` p1 (monzo_20240330 SH02): the date `14/03/2024` is not in the OCR text of that scan. OCR limit.
- `s08` p10 (revolut_20210519): `£1,000,000` is read as `E1,000,000`. The router flags OCR glyph faults like this and never rewrites them, by policy (`data/uk/sh01/README.md`). Deliberate miss.

## Table golden set v1 (63 rows, data/sec)

File: `evals/golden/golden_table_v1.jsonl` (copied to `data/golden/`). Seven rows per 10-K/10-Q/earnings filing where the row label has no digits, the value has 2+ digits, and the label and value both appear on the cited page of pymupdf text. Rows are sampled with seed 7. Scanned or image-only forms are not included.

Caveat: these rows were selected from the same text layer that the router and pymupdf read, so this set cannot separate those engines well. Each row still needs a hand check against the rendered page before it counts as a true golden item. The `verified` field says so.

| Engine | Page hit | Row hit | Bbox on row | s/page |
|---|---|---|---|---|
| pypdf | 63/63 | 62/63 | 0 | 0.12 |
| pymupdf_text | 63/63 | 63/63 | 0 | 0.03 |
| pdfplumber | 63/63 | 56/63 | 63 | 0.25 |
| router | 63/63 | 63/63 | 63 | 0.34 |

The router keeps every row with a bbox, at about 0.34 s/page. pdfplumber misses 7 rows, mostly where the value sits in a separate cell.

## Table golden set v1, hand-checked (78 rows)

Hand check: each of the 63 text-layer rows was rendered as a tight crop of its row from the cited page and read against the golden label and value. All 63 match after one fix. `tb17` (AMD FY2022, `Net income for diluted earnings per share`, $1,320) first looked wrong because its crop landed on the basic-EPS line, which carries the same $1,320. Re-rendered on the diluted line, the label and value match, so the golden row was right and the crop was wrong.

Scanned rows: 15 more rows point at image-only copies of the same pages (`data/sec_scan/`, rasterised at 200 dpi, no text layer). These rows were located on the text-layer original but not read on the scan, so they are `hand_read: false`.

| Engine | Text rows (63) | Scanned rows (15) | Bbox on row | s/page |
|---|---|---|---|---|
| pypdf | 62/63 | 0/15 | 0 | 0.10 |
| pymupdf_text | 63/63 | 0/15 | 0 | 0.03 |
| pdfplumber | 56/63 | 0/15 | 73 total | 0.22 |
| router | 63/63 | 14/15 | 105 total | 0.67 |

The scanned rows split the engines: only the router, which OCRs pages with no text layer, reads them. The router takes about 0.67 s/page, up from 0.34 s/page on text-only rows, because of the OCR pages.

## Synthetic investor deck and CIM (SYNTHETIC, not real filings)

Built by `evals/synthetic_deck_eval.py`. Every page is labelled `SYNTHETIC:`. Truth values are known by construction, so these are measured, not hand-checked.

| Page | Content | Result |
|---|---|---|
| Deck p1 | Financial table, 4 rows x 3 years (12 values) | 12/12 row hit (router, text layer) |
| CIM p1 | Financial table, same rows (12 values) | 12/12 row hit (router, text layer) |
| Deck p2 | Stacked bar, Segment A 120/150/180 and Segment B 80/95/110, bar labels | 6/6 landed with bbox (Qwen2.5-VL-3B, `ocr` source) |
| Deck p3 | Line chart, 12.5% / 14.0% / 15.5% value labels | 3/3 landed with bbox |

Chart notes: the model also reads axis ticks on p2 (0, 50, 100, 200, 250, 300). These are printed numbers, not segment values, so they land as `ocr_unverified` too. The eval field is renamed `other_numbers_read` to say that. The model reads no wrong segment values. Chart numbers still never auto-verify.

Gaps: one bar chart and one line chart, clean vector render, no real layout. CIM charts are not scored, and there are no multi-series charts with a legend, log axes, or scanned charts. These numbers do not show real-deck accuracy.

## Real investor decks, hand-labelled (5 decks, 26 labelled items)

Source: EDGAR 8-K exhibit PDFs (search via efts, filtered to PDF exhibits). Files copied to `data/real_decks/`. Labels in `evals/golden/golden_real_decks_v1.jsonl` were read off rendered page images (110 dpi), not the text layer. Scored by `evals/real_deck_eval.py`.

Decks used: MIMEDX Oct 2025 investor deck p12; Ampco-Pittsburgh Aug 2023 investor deck p29; Daseke Feb 2023 p18, May 2023 p23, Nov 2023 p7 (earnings presentations).

| Path | Labelled | Result |
|---|---|---|
| Router, table rows (25 rows, 105 values) | 105 values | 17/105 values on the labelled row line; 3/25 whole rows |
| Router, chart waterfall (Daseke p7, 9 values) | 9 values | 0 landed with bbox; the VLM returned no labels for the crop |
| OCR only on the same crop | 9 values | all 9 labels read with bbox (chart path uses OCR as its check) |

Why the table path misses: on these decks the text layer comes out one cell per line. The router's line grouping then splits rows across lines, so "row label + all values on one line" fails. This is the main gap for real decks, not the number parsing.

Gaps: 5 decks, not 10; 26 labelled items, not 50. Charts: one vector waterfall only. Lands' End and PGT PDFs were downloaded but not labelled. Hand labels are read from images, not double-checked.


## Table engines on real decks (99 table values, 19 labelled rows)

`evals/real_deck_table_engines.py`, same hand labels, table rows only (the 6 KPI tiles are excluded).

| Engine | Values on the labelled row line | Whole rows | Bbox |
|---|---|---|---|
| router (current) | 16/99 | 2/19 | yes |
| pymupdf words, y-overlap grouping | 16/99 | 2/19 | yes |
| pdfplumber | 58/99 | 3/19 | yes |
| pdftotext -layout | 99/99 | 19/19 | no |
| router + layout fallback | 99/99 (83 via layout) | 19/19 | 16 with bbox, 83 text-only |

Existing golden sets, same run (`pdf_benchmark.py`): pdftotext_layout is worse than router on sh01 (4/18 page vs 16/18) and has no bbox. So it is not a router replacement. Using it only as a fallback keeps the existing sets as they are.

Open: a layout-only hit has no bbox, so it cannot cite a location. It must not auto-verify. OCR chart fallback and the other 5 decks are not done.
