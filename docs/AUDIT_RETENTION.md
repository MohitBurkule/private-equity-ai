# Audit trail: growth and retention

The audit trail is one hash chain per tenant (`audit_event`, `app/audit.py`). Every row stores `prev_hash` and
its own `hash`, and `verify_chain` checks the whole chain. Because of that, rows cannot be deleted or
partitioned away in place without breaking verification.

## Why it grows fast

Every document opened through the API writes a `document.read` row (added with the access-report work).
A busy tenant can add thousands of rows a day from reads alone. Facts, exports and digests add more.

## Recommended approach

1. **Archive, don't delete.** Once a calendar month is closed, export its rows to a sealed file (JSON lines,
   with the last row's `hash` as the anchor) and store it with the retention policy for the deal.
2. **Keep the anchor.** The first row of the next month still has `prev_hash` pointing at the archived
   month's last hash. `verify_chain` can then run over the live table plus the archives in order.
3. **Partition by month only after step 1.** Partitioning the live table is fine once archives exist,
   because each partition is just a range of the same chain.
4. **Read-audit sampling is a policy choice.** If volume is a problem, log one `document.read` per user,
   document and hour instead of per request. That is a change to `_own_doc`; it is not done here.

## Not done in code

No archival job, no partitioning, no retention setting. Those need a decision on the retention period and
where archives live. Until then the table grows without a limit.
