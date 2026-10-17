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

## Held-out set (20 new exhibits, scored once, no rule changes after)
Labelled from the filed text first (`evals/legal_gold_heldout.json`), then rules run once. No regex was changed after scoring; the misses below are reported, not fixed.

| term | gold positives | precision | recall | tp / fp / fn |
|---|---|---|---|---|
| governing law | 20 | 1.00 | 0.95 | 19 / 0 / 1 |
| termination fee | 5 | 0.80 | 0.80 | 4 / 1 / 1 |
| non-solicit (months) | 3 | 1.00 | 0.67 | 2 / 0 / 1 |
| escrow (presence) | 19 | 1.00 | 0.89 | 17 / 0 / 2 |
| material adverse effect (presence) | 19 | 1.00 | 1.00 | 19 / 0 / 0 |

Misses and the cause in each case:
- **Governing law, J&J Snack (785956):** "governed and interpreted under the Laws of the State of Delaware". The pattern needs "by" after "governed". Not fixed here.
- **Termination fee, Lantheus (1521036):** an amendment sentence ("the amount of the Reverse Termination Fee shall thereafter be equal to $15,000,000") comes before the original $10,000,000 fee. The rule takes the first match. Which fee is current depends on the amendment's date condition; the gold uses $10,000,000. A rule-level question, not a regex bug.
- **Non-solicit, Sabre (1597033):** "until the second (2nd) anniversary of the Closing Date". No month or year word, so not read. Gold is 24.
- **Escrow, VSE (102752) and Lantheus (1521036):** the rule needs an escrow amount in the same sentence. Both exhibits name an escrow fund or "Adjustment Escrow Amount" without a figure in this text. **Gold conflict:** the gold labels mark these as present, but the labelling rule was "an escrow amount is stated". By that rule both should be absent and the rules are right. Left as labelled, not relabelled after scoring.

### Reader false-finding sample
Reader (local gemma 9B) run on the held-out terms the rules did not find, on the gold-null cases. A false finding is a reader value on an exhibit labelled null. Run on CPU is slow (minutes per call), so the sample is small: see the result line below.

**Result:** 2 exhibits finished (1364885 Spirit, 1599489 Veritiv): 0 false findings out of 3 reader calls (Spirit: non-solicit only, since the rules had found its fee; Veritiv: fee and non-solicit). The third exhibit did not finish before the run was stopped, so the false-finding rate is unmeasured beyond these 2. Reader recall on the held-out misses is also not measured; the rules already catch 19 of 20 governing-law and 17 of 19 escrow positives.

## Current status (both sets)
- Rules precision is 1.00 on the tuning set and 0.80 to 1.00 on the held-out set. The tuning set (28) is optimistic: its misses were fixed on it. The held-out set is the honest estimate, and it is still small.
- Recall on held-out is 0.67 to 1.00 by term. Known misses are listed above.

## Caveats (read these before quoting the numbers)
- 28 + 20 exhibits is a small sample. One miss moves recall by 4 to 20 points depending on the term.
- The gold was labelled by one reader. The Vacasa termination fee label was revised after the rules output was seen (rules had the $6,000,000 Parent Termination Fee in the text on page 53, and the $6,500,000 expense cap on page 34). The text supports the revised label, but it is a revision and is listed here.
- Escrow and MAE are presence labels only. They do not check the amount or the meaning.
- **Reader:** on these 28 exhibits the rules already find every gold-positive term that the reader is meant to catch, so there are no reader positives to score for recall. Reader precision (false findings) was not measured on this set; the full reader run was too slow on this CPU container and was stopped. The reader's positive case remains the GBTG exhibit (`apps/api/tests/test_flagship.py`, amount-first termination fee).
- Scope: these are merger exhibits. NDAs, credit agreements and 10-K text are not in this set.

## Not yet covered
Reader precision on this set, and the rules' remaining false-positive types (for example, a fee cap written as a fee). Next: run the reader on the gold-null terms of these 28 exhibits to measure false findings.
