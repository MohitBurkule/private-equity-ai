# Legal term benchmark (merger exhibits)

Run: `python evals/legal_benchmark.py --data DIR --no-reader` (rules only) or without `--no-reader` (adds the local-model second reader, needs `LLM_PROVIDER=llamacpp` and a gguf). `DIR` holds the filed exhibits named `<cik>_<accession>.htm`. Gold: `evals/legal_gold.json`. Harness scores `apps/api/app/legal.py` (rules) and `apps/api/app/legal_reader.py` (reader).

## Set
28 operating-company merger and amendment exhibits filed as EX-2.1 / EX-10 / EX-99 on EDGAR, 2022 to 2026. Two multi-agreement filings (a 2,700-page German-law Gentherm bundle and an EVERTEC share purchase bundle) were dropped before labelling because the "main agreement" is ambiguous. SPACs excluded.

## Gold
Hand-read from the filed text, one label per term per exhibit. A value is null when the exhibit does not state the term itself; cross-references to a merger agreement that is not filed here count as not stated. Escrow and material adverse effect are presence labels (is there an escrow amount, is an MAE term used). Non-solicit is the duration in months.

## Results (rules, 28 exhibits)
| term | gold positives | precision | recall | tp / fp / fn |
|---|---|---|---|---|
| governing law | 17 | 1.00 | 1.00 | 17 / 0 / 0 |
| termination fee | 5 | 1.00 | 1.00 | 5 / 0 / 0 |
| non-solicit (months) | 1 | 1.00 | 1.00 | 1 / 0 / 0 |
| escrow (presence) | 3 | 1.00 | 1.00 | 3 / 0 / 0 |
| material adverse effect (presence) | 7 | 1.00 | 1.00 | 7 / 0 / 0 |

### Before the fixes in this change
| term | precision | recall | tp / fp / fn | misses / false positives |
|---|---|---|---|---|
| governing law | 1.00 | 0.88 | 15 / 0 / 2 | "governed in all respects by" (Sanuwave); "Laws (excluding ...) of the State of Delaware" (Ideanomics) |
| termination fee | 0.80 | 1.00 | 4 / 1 / 0 | Vacasa: "exceed $6,500,000" is an expense cap, not the fee |
| non-solicit (months) | - | 0.00 | 0 / 0 / 1 | "four (4) years" not read, and duration before "solicit" not matched (Ideanomics) |

## Fixes made
- Governing law: the clause may say "governed in all respects by" and may have a parenthetical between "Laws" and "of".
- Non-solicit: years count (4 years = 48 months), and the duration may come before the word "solicit".
- Termination fee: a match may not run through the word "exceed" (an expense cap is not a fee).

## Caveats (read these before quoting the numbers)
- 28 exhibits is a small sample. One miss moves recall by 4 to 20 points depending on the term.
- The gold was labelled by one reader. The Vacasa termination fee label was revised after the rules output was seen (rules had the $6,000,000 Parent Termination Fee in the text on page 53, and the $6,500,000 expense cap on page 34). The text supports the revised label, but it is a revision and is listed here.
- Escrow and MAE are presence labels only. They do not check the amount or the meaning.
- **Reader:** on these 28 exhibits the rules already find every gold-positive term that the reader is meant to catch, so there are no reader positives to score for recall. Reader precision (false findings) was not measured on this set; the full reader run was too slow on this CPU container and was stopped. The reader's positive case remains the GBTG exhibit (`apps/api/tests/test_flagship.py`, amount-first termination fee).
- Scope: these are merger exhibits. NDAs, credit agreements and 10-K text are not in this set.

## Not yet covered
Reader precision on this set, and the rules' remaining false-positive types (for example, a fee cap written as a fee). Next: run the reader on the gold-null terms of these 28 exhibits to measure false findings.
