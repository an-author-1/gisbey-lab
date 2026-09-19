# Relational operators, full 20-page field (Phase 1)

Scales the same four operators (ECHO, DEVELOP, CONTRADICT, BRIDGE — wording unchanged,
quoted in `notes/relational-operators-experiment.md`) across every page in the corpus as
source, once each, canonical candidate order, no shuffling. 80 calls, all pinned to
`jev-1.13.0` explicitly, all succeeded. Does not modify or overwrite any prior experiment
record. One-off script, not a permanent case type or CLI command, reusing the existing
context/adapter/validator/recorder/runner unchanged.

Full machine-readable edge list: `runs/relop-full-field-edges.csv`. Per-run records: 80
directories under `runs/20260919T22*_relop-full-<source>-<operator>_live/`.

## 1. Matrix

| Source | Echo | Develop | Contradict | Bridge |
| --- | --- | --- | --- | --- |
| F1 | F9 (0.36) | F4 (0.34) | P1 (0.51) | P3 (0.30) |
| F2 | F4 (0.30) | F4 (0.74) | P1 (0.23) | P1 (0.15) |
| F3 | F4 (0.28) | F4 (0.79) | P1 (0.16) | P3 (0.21) |
| F4 | F3 (0.39) | F3 (0.35) | P1 (0.22) | P3 (0.18) |
| F5 | F7 (0.37) | F7 (0.49) | P1 (0.46) | P1 (0.18) |
| F6 | P5 (0.43) | F4 (0.29) | P1 (0.25) | P3 (0.23) |
| F7 | F5 (0.59) | F8 (0.43) | F8 (0.83) | P1 (0.19) |
| F8 | F1 (0.28) | F7 (0.25) | F7 (0.29) | P1 (0.20) |
| F9 | F10 (0.53) | F10 (0.40) | P1 (0.22) | P1 (0.13) |
| F10 | F9 (0.56) | F4 (0.39) | P1 (0.29) | P3 (0.25) |
| F11 | F10 (0.69) | F10 (0.27) | P1 (0.72) | F10 (0.17) |
| F12 | P8 (0.96) | F4 (0.16) | P6 (0.53) | P3 (0.27) |
| P1 | P2 (0.66) | P2 (0.31) | F11 (0.38) | P2 (0.32) |
| P2 | P3 (0.93) | P3 (0.99) | P3 (0.70) | P3 (0.57) |
| P3 | P2 (0.95) | P2 (0.31) | P2 (0.61) | F4 (0.18) |
| P4 | P8 (0.58) | P8 (0.25) | P7 (0.51) | P3 (0.46) |
| P5 | F5 (0.12) | P3 (0.20) | F11 (0.23) | P3 (0.22) |
| P6 | F12 (0.46) | F12 (0.35) | P7 (0.33) | P3 (0.18) |
| P7 | P6 (0.64) | P6 (0.38) | P6 (0.33) | P6 (0.11) |
| P8 | F12 (0.99) | F12 (0.62) | P6 (0.22) | F12 (0.30) |

## 2. Edge table

See `runs/relop-full-field-edges.csv` (80 rows: source, operator, destination, confidence,
model_version, run_dir). All 80 rows have `model_version = jev-1.13.0`. The same data is
in the matrix above in grid form; the CSV is the flat edge-list form, meant for feeding
into graph-shaped follow-up (e.g. does the field look like a small number of hub pages
with many inbound edges, per flag E below).

## Confidence distribution (n=80, before any threshold was assumed)

min 0.11, max 0.99, mean 0.4025, median 0.33, stdev 0.2247.
Q1 0.23, Q2 (median) 0.33, Q3 0.53, IQR 0.30.
p10 0.18, p90 0.722.
Standard IQR fence: low = Q1 - 1.5*IQR = -0.22 (below the possible range, so no values
qualify as low outliers by that rule); high = Q3 + 1.5*IQR = 0.98 (2 values exceed it).
Because the low fence falls outside the data's range, flag B below uses the bottom decile
(<= p10) as the practical low tail instead of the (empty) IQR-outlier set.

## A. Operator collisions (>= 2 operators from the same source share a destination)

19 of 20 sources have at least one collision; only F6 has none.

| Source | Destination | Operators |
| --- | --- | --- |
| F2 | F4 | ECHO, DEVELOP |
| F2 | P1 | CONTRADICT, BRIDGE |
| F3 | F4 | ECHO, DEVELOP |
| F4 | F3 | ECHO, DEVELOP |
| F5 | F7 | ECHO, DEVELOP |
| F5 | P1 | CONTRADICT, BRIDGE |
| F7 | F8 | DEVELOP, CONTRADICT |
| F8 | F7 | DEVELOP, CONTRADICT |
| F9 | F10 | ECHO, DEVELOP |
| F9 | P1 | CONTRADICT, BRIDGE |
| F11 | F10 | ECHO, DEVELOP, BRIDGE |
| P1 | P2 | ECHO, DEVELOP, BRIDGE |
| P2 | P3 | ECHO, DEVELOP, CONTRADICT, BRIDGE (all four) |
| P3 | P2 | ECHO, DEVELOP, CONTRADICT |
| P4 | P8 | ECHO, DEVELOP |
| P5 | P3 | DEVELOP, BRIDGE |
| P6 | F12 | ECHO, DEVELOP |
| P7 | P6 | ECHO, DEVELOP, CONTRADICT, BRIDGE (all four) |
| P8 | F12 | ECHO, DEVELOP, BRIDGE |

Two sources — P2 and P7 — got the *same* destination from all four operators (P2->P3 and
P7->P6 respectively). Both are reciprocal: P3's own operators mostly point back to P2, and
P6's operators mostly point back to P7 (P6/CONTRADICT and P6/BRIDGE both -> P7). That's a
candidate for a genuinely tight two-page bond rather than an operator-differentiation
failure, but it's also exactly the pattern worth checking isn't a corpus artifact (e.g.
unusually similar or short pages) before treating it as literary signal.

## B. Low confidence (bottom decile, confidence <= 0.18; ties included, n=11)

| Source | Operator | Destination | Confidence |
| --- | --- | --- | --- |
| P7 | BRIDGE | P6 | 0.11 |
| P5 | ECHO | F5 | 0.12 |
| F9 | BRIDGE | P1 | 0.13 |
| F2 | BRIDGE | P1 | 0.15 |
| F3 | CONTRADICT | P1 | 0.16 |
| F12 | DEVELOP | F4 | 0.16 |
| F11 | BRIDGE | F10 | 0.17 |
| F4 | BRIDGE | P3 | 0.18 |
| F5 | BRIDGE | P1 | 0.18 |
| P3 | BRIDGE | F4 | 0.18 |
| P6 | BRIDGE | P3 | 0.18 |

BRIDGE accounts for 7 of these 11 (64%) despite being 1 of 4 operators (25% of all runs) —
BRIDGE is disproportionately the low-confidence operator across the whole field, not just
for F9 as seen in the earlier diagnostic.

## C. NONE selections

None. 0 of 80 runs abstained.

## D. Strong edge (confidence >= 0.722 top decile; the 2 strict IQR outliers above 0.98 are marked *)

| Source | Operator | Destination | Confidence |
| --- | --- | --- | --- |
| P2 | DEVELOP | P3 | 0.99 * |
| P8 | ECHO | F12 | 0.99 * |
| F12 | ECHO | P8 | 0.96 |
| P3 | ECHO | P2 | 0.95 |
| P2 | ECHO | P3 | 0.93 |
| F7 | CONTRADICT | F8 | 0.83 |
| F3 | DEVELOP | F4 | 0.79 |
| F2 | DEVELOP | F4 | 0.74 |

F12<->P8 and P2<->P3 each appear twice in this list in *both directions* (F12->P8 and
P8->F12; P2->P3 and P3->P2), which is the strongest evidence in this dataset of reciprocal,
high-confidence bonds rather than one-way high scores.

## E. Destination attractors (selected across unusually many source/operator pairs)

Frequency across all 80 picks (0 NONE, so 80 substantive picks), mean 4.71/destination,
stdev 3.98:

| Destination | Count |
| --- | --- |
| P1 | 14 |
| P3 | 14 |
| F4 | 9 |
| P6 | 6 |
| P2 | 6 |
| F10 | 5 |
| F12 | 5 |
| F7 | 4 |
| P8 | 3 |
| F9, F3, F5, F8, F11, P7 | 2 each |
| P5, F1 | 1 each |

P1 and P3 are each selected in 14 of 80 runs (>3x the mean, and above mean+2*stdev), a
clear outlier gap above F4 (9, the next highest). P1's pulls are concentrated in
CONTRADICT and BRIDGE (13 of its 14 selections); P3's are spread across all four operators
(most from ECHO/BRIDGE). This is the strongest single finding in the field map: two pages
are functioning as attractors, but for what look like different structural reasons —
P1 as a default "tension/distance" destination, P3 as a broadly resonant one.

## Where this points for targeted follow-up

* P1 and P3 as attractors: worth checking whether this is a property of their content
  (short, general-purpose, or unusually central passages) or a positional/corpus-structure
  artifact, similar to the order-sensitivity check already run on F9/BRIDGE.
* BRIDGE's disproportionate share of the low-confidence tail (7/11) is now a field-wide
  pattern, not a single-source anomaly — a candidate for its own targeted diagnostic before
  BRIDGE's results are treated with the same weight as the other three operators.
* P2<->P3 and P7<->P6 as candidate reciprocal bonds (all-four-operator agreement, one pair
  also appearing in the strong-edge list) are worth a dedicated closer read, distinct from
  the F12 comparison work already done.
* All of the above is Phase 1 (canonical order only, single run per pair). No shuffled
  duplicates have been run at full-field scale — order-sensitivity across all 80 pairs
  remains open.
