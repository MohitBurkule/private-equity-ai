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

### Fixes after the held-out run (not in the numbers above)
Two held-out misses fixed in code, each with a regression test: governing law "governed and interpreted under the Laws of ..." (no "by"), and non-solicit "second (2nd) anniversary" = 24 months. The held-out table and results above are kept as scored, before these fixes. The termination fee amendment ordering and the escrow "fund without amount" question are not changed; they need a decision. The next fresh set measures these fixes.

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

## Lease and employment (GAPS #13)
Doc types `lease` and `employment` added. Terms: `governing_law`, `change_of_control`, `assignment` (lease, employment), `termination_notice_days` (lease, employment), `non_compete_months` (employment), `severance` (employment). Playbook rules: `assignment_restricted`, `employment_non_compete_long` (over 12 months), `termination_notice_short` (under 30 days), `severance_present` (review).

Set: 12 lease and 17 employment exhibits from EDGAR 8-K filings (full-text search, EX-10 type), in `evals/legal_gold_lease_employment.json` (`doc_type` per entry). Run: `python evals/legal_benchmark.py --data <dir with lease/ and employment/> --gold evals/legal_gold_lease_employment.json --no-reader`.

**Caveat, read first:** these labels were written after the new rules ran on these exhibits, then spot-checked against the text. This is a tuning-style set, not held-out, so the numbers are optimistic. The reader was not run on it.

| term | precision | recall | tp/fp/fn |
|---|---|---|---|
| governing_law | 1.00 | 1.00 | 16/0/0 |
| change_of_control | 1.00 | 1.00 | 14/0/0 |
| severance | 1.00 | 1.00 | 17/0/0 |
| assignment | 0.93 | 0.93 | 14/1/1 |
| non_compete_months | 0.86 | 1.00 | 6/1/0 |
| termination_notice_days | 0.67 | 1.00 | 4/2/0 |

Known errors:
- Assignment FN: PPIH 0001437749-25-011051 "not assignable to another person without prior written consent" (no rule pattern for "not assignable").
- Assignment FP: DUKE 0001213900-26-067570 "shall not be required to bear any expenses" matched by the keyword.
- Termination notice FP: Foghorn 0001628280-25-033784 "60 days prior written notice" is for ending a shuttle service, not the lease. WillScot 0001647088-25-000050 "60 days" is a Good Reason cure notice, not a termination notice.
- Non-compete FP: Fidelity & D&D 0001437749-25-038321 is an amendment that reduces a covenant; the rule reads the 24 months, the label is null.
- Governing law recall was fixed for "construed ... in accordance with", "Commonwealth of", and "laws of the United States and the State of"; no misses left in this set.

Not covered: lease rent and term; change-of-control language that is a consent right rather than a payment trigger (labelled present, not classified); equity-plan "may not be assigned" clauses inside employment agreements (not counted in gold, not filtered in code).

Next: a fresh lease and employment set, labelled before rules run, to measure these terms honestly.


## Fresh lease and employment set (after the #413 fixes)
20 new exhibits (10 lease, 10 employment; EDGAR EX-10 via full-text search, none in the #413 set). `evals/legal_gold_fresh_lease_employment.json`.

Gold was written from keyword-sentence dumps before the rules ran. Then 12 values were corrected after reading the rule quotes, because the dump had missed sentences (uppercase, "construed and enforced" wording, notice wording). Both scores are below.

| term | blind P / R (tp/fp/fn) | corrected P / R (tp/fp/fn) |
|---|---|---|
| governing_law | 0.55 / 0.86 (6/5/1) | 1.00 / 0.92 (11/0/1) |
| assignment | 0.55 / 1.00 (6/5/0) | 0.91 / 1.00 (10/1/0) |
| change_of_control | 0.86 / 1.00 (6/1/0) | 1.00 / 1.00 (7/0/0) |
| severance | 1.00 / 1.00 (10/0/0) | 1.00 / 1.00 (10/0/0) |
| termination_notice_days | 0.00 / 0.00 (0/3/1) | 0.00 / 0.00 (0/3/1) |

Read the corrected column as optimistic: the corrections came from looking at the rules' output.

Known errors:
- Termination notice: 3 FPs. Two lease holdover and eminent-domain "30 days" sentences (Colorado PSA and amendment), one parking-lot "30 days" (Body & Mind). One FN: "Any such termination shall be effective thirty (30) days after the giving of such notice" (Mercantile). This term is the weakest; do not quote it.
- Governing law FN: none in the corrected set except one. Blind misses were "construed and enforced in accordance with the laws of the State of" and uppercase text; the regex now reads both.
- Assignment: 1 FP in the corrected set.
- Amendments that reduce a non-compete (Fidelity 038783) are labelled null and the rule now skips them on purpose.

Termination fee ordering (open item, decided): a fee sentence with "instead of" or "thereafter" is still reported but now flagged `needs_review`. The held-out Lantheus 1521036 value stays $15,000,000 as scored, against gold $10,000,000. Gold reading is the base fee; the amendment raises it to $15M on a condition. Not changed in the held-out numbers above.

Also fixed in this pass: "not assignable" is now a restriction; "shall not be required" is not; a non-compete inside an amendment that reduces it is skipped; a "notice ... days" phrase that ends in "service" or "within" is skipped.
