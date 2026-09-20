# src/

Loader, context assembler, Jev adapter, proposal validator, run recorder, and reader-state handling.

Implemented as the `gibsey_lab` package: `corpus.py` (training-corpus loader/manifest),
`holdout_corpus.py` (holdout-corpus loader), `fields.py` (the two candidate fields the
reader operates over), `sentence_map.py`, `cases.py` + `context.py` (f12-micro/f12-macro
case specs and assembly), `relational_operators.py` (frozen Q Operator Prototype v0.1
wording), `reader_context.py` (context assembly for the reader), `jev_client.py` (real
adapter) / `mock_client.py` (deterministic offline adapter), `validate.py`, `recorder.py`,
`saved_runs.py` (recorded-result lookup, verified by field/version/criterion/model),
`reviewing.py` (optional review notes), `session_log.py` (passive automatic session-route
log), `session_review.py` (gathers exact recorded text for agent review, no confidence),
`runner.py`, `state.py` (Q/R actions), `cli.py` (the `gibsey` command), and `reader/` (the
local browser reader — see the root `README.md`, "Local browser reader"). The
`.claude/agents/` and `.claude/skills/review-reading-session/` directories hold the
read-only agent review setup described there too.
