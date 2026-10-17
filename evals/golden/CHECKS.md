# Golden set checks (local pass)
- Each JSONL line is one item: id, question, answer, sources, tags, notes, verified.
- Every `html-text` quote was machine-matched against the normalised filing text when written.
- `ixbrl` and `xbrl-api` sources cite accession numbers; values were auto-crosschecked against companyfacts (see golden_xbrl_v1.jsonl verified fields).
- Known unresolved items are marked in notes (for example KKR 1976 Fund MOIC 17.1x vs 537/31 = 17.3x).
- Source filings are not in this repo; they live in the shared project files.
