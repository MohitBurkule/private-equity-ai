# Review queue (GAPS #8)

## What already existed
- Fact statuses: `verified` (passed the citation gate), `ocr_unverified` (quote came from OCR text), `rejected`.
- `GET /facts?status=` lists the queue; `POST /facts/{id}/review` accepts, rejects or edits.
- Edits re-run the citation gate, and every review is audited with before and after values.
- The memo reads `verified` facts only.

## Gap closed here
The agent's `list_facts` tool returned every non-rejected fact as "verified", so OCR facts nobody had accepted could be cited in answers. It now returns `verified` only.

## Design calls
- `ocr_unverified` stays out of memos, calculations and agent answers until accepted. Conflict detection still includes it, because a conflict is worth reporting even before review.
- The queue stays a filter on `GET /facts`, not a separate table. One row per fact keeps the audit trail in one place.
- The `auto` default status is left alone. Nothing writes it, and removing it would need a migration for no behaviour change.

## Not done
- Per-reviewer queues and assignment. Needs the roles model from GAPS #1 first.
