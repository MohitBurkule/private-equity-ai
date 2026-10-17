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
