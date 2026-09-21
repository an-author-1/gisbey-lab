# Lead live verification, 2026-09-20 (NOT the reader's session)

Records from a scratch reader instance (port 8791, temporary session stores) that the
lead agent used once to verify the live HTTP path end to end: a scripted path
LF3 → LF4, one live offers request at LF4 (two simultaneous identical clicks → one
dispatch set), then follow-time validation probes and one follow LF4 → LF11.

- These are **not the user's actions** and not accepted bonds of the user's session; the
  `bonds.json` / `reader_state.json` / `session_log.jsonl` here belong to the scratch
  session only and are never read by the reader.
- `contextual_assessments.jsonl` holds the two **live** history-conditioned assessments
  (LF4→LF14, LF4→LF11; jev-1.13.0; 2,190 + 2,247 input tokens). Their budget entries are
  the two reservations in `data/reader_ledger.jsonl` at 19:22:30Z. They are kept here,
  out of `data/contextual/`, so they are never reused as cache for a real session.
- At the time of writing these were the only live contextual assessments built from a
  session-log packet; the 15 in `data/contextual/` are PR2 demonstration fixtures.
