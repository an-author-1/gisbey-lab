# Core v0.3 session 2 — mixed-journey demonstration (lead, 2026-09-25) — NOT Brennan's session

Isolated reader instance (temp stores, real live atlas read-only, mock provider never
called) driven in headless Chrome by the lead's `demo.py` (results in
`browser_demo_result.json`). One session, `s_10169fa2df45`, throughout:
start P1 → Q DEVELOP → P5 → Next (P6) → Previous (P5, return) → page list (P1, return) →
in-app Back (P5) → browser Back (P1) → browser Forward (P5) → Q ECHO → P1 → refresh →
SIGTERM + restart + reload → scripted identical retry (duplicate, same encounter) →
conflicting request-id reuse (409 request_id_reused) → second tab moves, first tab's
click → 409 stale_revision with explanation, re-synced. Journey page: 11 encounters once,
in order, kinds labeled; 7 return markers. `core/sessions/<id>/events.jsonl` is the
journal (14 events incl. one journaled rejection); `journey_<id>.json` is the bundle with
retained prose and the replay result (state OK, decision OK — 2 offer sets, none invented
for manual moves; 0 provider calls).
