# Golden sets (v1)
- `golden_v1.jsonl` (18): hand-checked. PDF page (1-based) + row + raw string, XBRL accn. Traps: sign, units, restatement vintages, YTD vs quarter, scanned PDF OCR, S-1 tiny issuer, non-calendar FY, gold error in FinanceBench (g02).
- `golden_xbrl_v1.jsonl` (117): auto-crosschecked. Value read from the filing's own inline XBRL (scale+sign applied) equals SEC companyfacts for same accn+concept+period. 10 companies, 10-K and 10-Q: Blackstone, KKR, Carlyle, Apollo, Ares, Dun & Bradstreet, Sotera Health, Hertz, Sandisk, Champions Oncology. 10-Q items carry ytd_alternates (answer is the quarter, not YTD). Concept in question text (restricted cash vs cash, attributable vs consolidated NI, equity excl. NCI). Second check: displayed number appears in the rendered filing text within 260 chars after the expected row label for 116/117 (x130, Champions operating loss (1,140), confirmed by hand: label is "Income (loss) from operations"). Hand-read in rendered filing text with surrounding row context: 14 more random items (x042,x043,x076,x078,x079,x084,x090,x094,x097,x099,x118,x121,x128,x129) all consistent, plus x130; so 15 of 117 read by hand. x076 note: consolidating-schedule column trap.
- `golden_uk_ixbrl_v1.jsonl` (45): Companies House micro-entity iXBRL, size-ranked from a random draw of one daily bulk file (NOT screened as PE targets). 11 fail internal arithmetic (tagged reliable:false); these are the edge cases.
Scoring: normalize scale/sign; require citation to file+concept+period (or page+row). For restatement items require naming the filing vintage. For unreliable items the correct system behaviour is to flag, not to answer.
- `golden_text_v1.jsonl` (29): text/table items from non-XBRL-numeric sources: Altria 8-K + Ex 99.1 (non-GAAP reconciliation, guidance, buybacks, exhibit-not-main-doc), 21Shares 8-K, Sandisk 10-K (segment/geography sums, 53-week year, term loan settled, covenant threshold absent, customer concentration), Cashlin S-1, XPO May 2026 credit agreement amendment and Term Loan A (8-K + Ex 10.1/10.2: springing maturity, pricing step-downs, covenants, unit differences), Hertz DEF 14A (summary compensation table with dash cells, sum rounding, pay ratio). Every quote machine-matched verbatim; arithmetic recomputed.

## Mapping to design/GAPS.md #7 extraction targets (golden_text_v1)
- debt schedule / covenants: t09 Sandisk, t15-t19 XPO credit docs, t25 Hertz debt table (two registrants, subtotal trap)
- management-adjusted EBITDA bridge: t21 Sotera (bridge ties, starts at adjusted net income, recurring add-backs)
- ARR / NRR / churn / customer counts: t22 Backblaze (ARR ties, customer counts do not, definitions)
- contract terms (exclusivity, termination, change of control, redactions): t23 Cerebras-OpenAI (130 redactions, absence is not evidence)
- cap table / JV equity / reserved matters / blocking: t24 Elmet-Blue Moon-EQ
- customer concentration: t10 Sandisk; governance: t20 KKR special-meeting proxy; comp tables: t12-t14 Hertz proxy
- sponsor-backed IPO prospectus (CIM-like): t26 Alliance Laundry 8-column adjusted EBITDA bridge (dropped blank cells), t27 Alliance Laundry capitalization/dilution/ownership (600-share inconsistency, secondary double count); t28-t29 Netskope S-1/A (ARR/NRR/GRR definitions, quarterly tie-outs, preferred stock + convertible notes capitalization)
- Not covered yet: full waterfall / liquidation preference stack, vintage cohort tables (Netskope S-1 has no cohort table, only the NRR cohort definition), true management CIM numbers (not public), MFN clauses (none found in the contracts read).

## golden_sh01_v1.jsonl (8, s01-s08)
Companies House SH01/SH02/SH19/SH20 share-capital forms (Monzo, Revolut), mostly scanned. Covers non-cumulative duplicate-date totals, consolidation continuity, non-cash allotments, OCR currency-symbol trap, hurdle-waterfall prescribed particulars, filing-history index vs form mismatches. PDFs in uk/sh01/.

Update 10: golden_text now 37 (t36-t37 Firefly preferred) (t33-t35 Klaviyo cohort/NRR/$50k-ARR), golden_xbrl now 122 (x136-x140: Ares revenue = segment vs GAAP trap, consolidating-column arithmetic, companyfacts Revenues vs contract-revenue concept divergence). Total golden: 18+122+45+35+8 = 230.
Update 11: golden_text 41 (t38-t41 Carlyle fund metrics). Total golden: 18+122+45+41+8 = 234 (+3 Fidus t42-t44, +4 Blackstone t45-t48 = 241).
