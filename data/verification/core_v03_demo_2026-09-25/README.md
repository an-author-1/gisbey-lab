# Core v0.3 persistent-Q demonstration (lead, 2026-09-25) — NOT the user's session

Isolated reader instance (temp session stores, real live atlas read-only, mock provider
never called; build f5847b0 + uncommitted session-1 changes, later committed). Driven in
headless Chrome by `demo.py` (kept in the scratchpad; results in
`browser_demo_result.json`): open P1 → DEVELOP → five supported bonds with offered
sentences → preview equals the vault text of P5 → Follow → reader shows P5's exact prose,
session revision 2, 2 encounters → browser refresh: unchanged → server SIGTERM + restart +
reload: same session, revision 2, 2 encounters → journey page shows exact prose, the
offer set, the selection, decision evidence and state before/after.

`core/sessions/s_0103376737a9/events.jsonl` is the journal (3 events). `journey_s_0103376737a9.json`
is the self-contained bundle with retained prose bytes and the provider-disabled replay
result (state replay OK, decision replay OK, 0 provider calls).
