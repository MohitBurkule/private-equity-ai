# Structured extraction schema (GAPS #7, first slice)

## Decisions
- Shapes are pydantic models in `apps/api/app/extraction_schema.py`: cap table rows, debt tranches, covenants, customer concentration, contract terms.
- Validators reject rows that cannot be true (negative shares, percentages over 100, customer shares above 100% of a period, non-positive covenant thresholds). A rejected row never reaches the citation gate.
- Passing the schema is not verification. Each row still becomes a Fact only through `add_verified_fact`, which checks the quote and number, and anything low-confidence stays in the review queue.
- Types are closed sets (`instrument`, `metric`, `operator`) so unknown labels fail loudly instead of becoming free text.

## Not done
- The extractor that produces these rows from documents. This slice is the typed contract and its validators only.
- Cap table and debt rows are not yet written to the fact table. Facts need a metric name per shape first.
