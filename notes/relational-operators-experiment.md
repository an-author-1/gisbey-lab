# Relational operators experiment (ECHO / DEVELOP / CONTRADICT / BRIDGE)

Goal: not to find one correct destination, but to test whether four distinct relational
instructions produce distinct, order-stable outgoing edges from the same source page. This
is a one-off experimental runner (not a permanent case type or CLI command) built on the
existing, unmodified context/adapter/validator/recorder/runner components. No baseline
records were altered.

## Method

* Sources: F12, F9, F3.
* Candidates: for each source, the other 19 authored pages (self-excluded, mirroring the
  existing f12-macro case's own exclusion rule) plus `NONE`.
* `NONE` option description reused as-is from `gibsey_lab.cases.ABSTAIN_TEXT` (same NONE
  behavior as every other case in this harness).
* Model: requested `jev-latest` for all 24 calls (same as both prior baseline runs).
* Each (source, operator) pair ran twice: once with candidates in the corpus's natural
  order (F-pages then P-pages, numeric), once with the 19 substantive candidates in a
  fixed, reproducible shuffled order (seeded per source: `relop-shuffle-<source>`; `NONE`
  kept last in both orders by design, so only substantive-candidate ordering varies).
* 24 live Choice calls total, all succeeded, all returned `jev-1.13.0` (no model drift
  from either prior run in this lab).

## Exact criterion text per operator

**ECHO:** Select the passage that most strongly returns to, mirrors, resonates with, or
meaningfully recurs from the source passage. Choose NONE if no candidate offers a
meaningful echo.

**DEVELOP:** Select the passage that most productively extends, complicates, develops, or
transforms what the source passage is doing. Choose NONE if no candidate offers a
productive development.

**CONTRADICT:** Select the passage that most meaningfully resists, reverses, destabilizes,
challenges, or creates tension with the source passage. Choose NONE if no candidate creates
meaningful tension.

**BRIDGE:** Select the passage that creates the strongest useful connection to the source
that is not primarily based on obvious surface similarity, repeated wording, or direct
thematic overlap. Choose NONE if no candidate offers such a connection.

## Rationale field

The TypeSafe Choice API does not return a rationale/explanation field (only `choice`,
`probabilities`, `confidence`, `usage`). No rationale is recorded per run because none was
returned — none has been invented or attributed to Jev in its place.

## All 24 results

| Source | Operator | Order | Destination | Confidence | Run directory |
| --- | --- | --- | --- | --- | --- |
| F12 | ECHO | original | P8 | 0.96 | runs/20260919T220706Z_relop-F12-echo-original_live |
| F12 | ECHO | shuffled | P8 | 0.97 | runs/20260919T220709Z_relop-F12-echo-shuffled_live |
| F12 | DEVELOP | original | F10 | 0.19 | runs/20260919T220707Z_relop-F12-develop-original_live |
| F12 | DEVELOP | shuffled | F10 | 0.30 | runs/20260919T220709Z_relop-F12-develop-shuffled_live |
| F12 | CONTRADICT | original | P6 | 0.42 | runs/20260919T220708Z_relop-F12-contradict-original_live |
| F12 | CONTRADICT | shuffled | P6 | 0.41 | runs/20260919T220710Z_relop-F12-contradict-shuffled_live |
| F12 | BRIDGE | original | P3 | 0.29 | runs/20260919T220708Z_relop-F12-bridge-original_live |
| F12 | BRIDGE | shuffled | P3 | 0.34 | runs/20260919T220711Z_relop-F12-bridge-shuffled_live |
| F9 | ECHO | original | F10 | 0.54 | runs/20260919T220711Z_relop-F9-echo-original_live |
| F9 | ECHO | shuffled | F10 | 0.48 | runs/20260919T220713Z_relop-F9-echo-shuffled_live |
| F9 | DEVELOP | original | F10 | 0.40 | runs/20260919T220712Z_relop-F9-develop-original_live |
| F9 | DEVELOP | shuffled | F10 | 0.37 | runs/20260919T220714Z_relop-F9-develop-shuffled_live |
| F9 | CONTRADICT | original | F8 | 0.25 | runs/20260919T220712Z_relop-F9-contradict-original_live |
| F9 | CONTRADICT | shuffled | F8 | 0.24 | runs/20260919T220714Z_relop-F9-contradict-shuffled_live |
| F9 | BRIDGE | original | P1 | 0.13 | runs/20260919T220713Z_relop-F9-bridge-original_live |
| F9 | BRIDGE | shuffled | **P3** | 0.26 | runs/20260919T220715Z_relop-F9-bridge-shuffled_live |
| F3 | ECHO | original | F4 | 0.25 | runs/20260919T220715Z_relop-F3-echo-original_live |
| F3 | ECHO | shuffled | F4 | 0.50 | runs/20260919T220717Z_relop-F3-echo-shuffled_live |
| F3 | DEVELOP | original | F4 | 0.79 | runs/20260919T220716Z_relop-F3-develop-original_live |
| F3 | DEVELOP | shuffled | F4 | 0.90 | runs/20260919T220718Z_relop-F3-develop-shuffled_live |
| F3 | CONTRADICT | original | P1 | 0.17 | runs/20260919T220716Z_relop-F3-contradict-original_live |
| F3 | CONTRADICT | shuffled | P1 | 0.10 | runs/20260919T220719Z_relop-F3-contradict-shuffled_live |
| F3 | BRIDGE | original | P3 | 0.19 | runs/20260919T220717Z_relop-F3-bridge-original_live |
| F3 | BRIDGE | shuffled | P3 | 0.22 | runs/20260919T220719Z_relop-F3-bridge-shuffled_live |

## Order-sensitivity flags

Only one of the twelve (source, operator) pairs changed destination when candidate order
was shuffled: **F9 / BRIDGE** (P1 at original order, confidence 0.13 → P3 at shuffled
order, confidence 0.26). Every other pair returned the same destination under both orders.
BRIDGE also carried the lowest confidence of any operator across all three sources (0.13,
0.19, 0.26, 0.29, 0.34), which is directionally consistent with it being the one order-
unstable case observed here — but this is a single instance, not a statistical claim.

## Comparison table (original order)

| Source | Echo | Develop | Contradict | Bridge |
| --- | --- | --- | --- | --- |
| F12 | P8 | F10 | P6 | P3 |
| F9 | F10 | F10 | F8 | P1 |
| F3 | F4 | F4 | P1 | P3 |
