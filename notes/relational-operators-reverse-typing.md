# Reverse operator typing: T(source, destination) -> operator

Tests whether the relational label that produced a forward edge is independently
recoverable from the resulting (source, destination) pair alone. Jev was shown both full
passages and asked to choose exactly one of ECHO / DEVELOP / CONTRADICT / BRIDGE / NONE
(descriptions given verbatim by the reader, not the operator's original criterion text) —
it was never told which operator(s) produced the edge. Operator definitions unchanged.
Model pinned to `jev-1.13.0` throughout (53/53 confirmed). No prior run record modified.
One-off script, not a permanent case type or CLI command.

Source data: `runs/relop-full-field-edges.csv` (80 forward edges) deduplicated by
(source, destination) -> 53 unique pairs (34 singleton, 19 collision), matching the
reader's own count exactly. Full reverse results: `runs/relop-reverse-typing-edges.csv`.
Per-run records: `runs/*_relop-reverse-<source>-<destination>_live/`.

## Headline result

Reverse classification overwhelmingly selected **DEVELOP**: 49 of 53 pairs (92.5%).
CONTRADICT: 3/53. ECHO: 1/53. BRIDGE: 0/53. NONE: 0/53.

DEVELOP's own definition ("extends, complicates, develops, or transforms") is broad enough
that it appears to function as a default/absorbing label under independent reread, not a
distinctively recoverable one. Every finding below should be read against that fact:
"reverse-selected DEVELOP" is the base rate, not a positive signal on its own.

## 1. Singleton recovery (n=34 pairs produced by exactly one forward operator)

Overall: 8/34 = 0.235.

| Forward operator | n | Recovered | Rate |
| --- | --- | --- | --- |
| ECHO | 7 | 1 | 0.143 |
| DEVELOP | 4 | 4 | 1.000 |
| CONTRADICT | 12 | 3 | 0.250 |
| BRIDGE | 11 | 0 | 0.000 |

DEVELOP's 100% is close to trivial here: it's the reverse classifier's own default, so a
DEVELOP-forward edge "recovering" as DEVELOP mostly confirms the classifier's baseline
behavior rather than demonstrating DEVELOP is distinguishable from the others.

## 2. Confusion matrix (singletons only)

| Forward \ Reverse | ECHO | DEVELOP | CONTRADICT | BRIDGE | NONE |
| --- | --- | --- | --- | --- | --- |
| ECHO (n=7) | 1 | 6 | 0 | 0 | 0 |
| DEVELOP (n=4) | 0 | 4 | 0 | 0 | 0 |
| CONTRADICT (n=12) | 0 | 9 | 3 | 0 | 0 |
| BRIDGE (n=11) | 0 | 11 | 0 | 0 | 0 |

Every single column outside DEVELOP and (for CONTRADICT) CONTRADICT itself is zero. ECHO
is weakly recoverable (1/7). CONTRADICT is partially recoverable (3/12) and — notably — is
the *only* operator other than DEVELOP that reverse classification ever selects at all.
**BRIDGE is not recovered once, in any of its 11 singleton pairs, and every one of them is
reclassified as DEVELOP.** This is a stronger and more specific finding than the earlier
forward-only observation that BRIDGE had the lowest confidence tail: here, independently
rereading BRIDGE-forward pairs never reproduces BRIDGE as a distinct relation.

## 3. Collision analysis (n=19 pairs produced by 2+ forward operators)

| Source | Dest | Forward set | Reverse | Confidence | In set? |
| --- | --- | --- | --- | --- | --- |
| F2 | F4 | ECHO, DEVELOP | DEVELOP | 0.97 | yes |
| F2 | P1 | CONTRADICT, BRIDGE | DEVELOP | 0.36 | no |
| F3 | F4 | ECHO, DEVELOP | DEVELOP | 0.96 | yes |
| F4 | F3 | ECHO, DEVELOP | DEVELOP | 0.62 | yes |
| F5 | F7 | ECHO, DEVELOP | DEVELOP | 0.97 | yes |
| F5 | P1 | CONTRADICT, BRIDGE | DEVELOP | 0.29 | no |
| F7 | F8 | DEVELOP, CONTRADICT | DEVELOP | 0.67 | yes |
| F8 | F7 | DEVELOP, CONTRADICT | DEVELOP | 0.89 | yes |
| F9 | F10 | ECHO, DEVELOP | DEVELOP | 0.94 | yes |
| F9 | P1 | CONTRADICT, BRIDGE | DEVELOP | 0.40 | no |
| F11 | F10 | ECHO, DEVELOP, BRIDGE | DEVELOP | 0.90 | yes |
| P1 | P2 | ECHO, DEVELOP, BRIDGE | DEVELOP | 0.78 | yes |
| **P2** | **P3** | **ECHO, DEVELOP, CONTRADICT, BRIDGE (all four)** | **DEVELOP** | **0.98** | yes |
| P3 | P2 | ECHO, DEVELOP, CONTRADICT | DEVELOP | 0.56 | yes |
| P4 | P8 | ECHO, DEVELOP | DEVELOP | 0.51 | yes |
| P5 | P3 | DEVELOP, BRIDGE | DEVELOP | 0.58 | yes |
| P6 | F12 | ECHO, DEVELOP | DEVELOP | 0.81 | yes |
| **P7** | **P6** | **ECHO, DEVELOP, CONTRADICT, BRIDGE (all four)** | **DEVELOP** | **0.71** | yes |
| P8 | F12 | ECHO, DEVELOP, BRIDGE | DEVELOP | 0.58 | yes |

Every single collision reverse-classified as DEVELOP — 19/19. Nominal "in-set" rate is
16/19 (84.2%), but that number is an artifact of DEVELOP already being in 17 of the 19
forward sets, not evidence of multi-relational richness. The two collisions whose forward
set *excludes* DEVELOP (F2->P1: CONTRADICT+BRIDGE; F5->P1: CONTRADICT+BRIDGE) both still
reverse-classify as DEVELOP, landing outside their forward set.

**P2 -> P3 and P7 -> P6**, the two pairs where all four operators agreed going forward,
both collapse to a single DEVELOP reading under independent reread — at high confidence in
P2->P3's case (0.98). This answers the reader's question directly: these read as **one
relational interpretation dominating**, not as genuinely multi-relational bonds. The
unanimous forward agreement looks like it was several operators converging on the same
"this productively extends the source" reading through different instruction wordings,
not four independent relations all holding simultaneously.

## 4. Attractor analysis: inbound to P1 and P3

**P1** (11 inbound unique pairs, all originally CONTRADICT and/or BRIDGE forward):
reverse distribution DEVELOP 8, CONTRADICT 3, BRIDGE 0. Majority DEVELOP, but P1 is the
*only* place in the entire 53-pair set where CONTRADICT survives reverse classification
more than once. **Partial answer to "does P1 still classify predominantly as
CONTRADICT/BRIDGE": no — DEVELOP is still the plurality/majority reading — but P1 retains
the only concentrated non-DEVELOP signal in the dataset.**

**P3** (10 inbound unique pairs, 9 originally BRIDGE and 1 the all-four-operator P2->P3
collision): reverse distribution DEVELOP 10, everything else 0. **P3's apparent "broader
relational profile" from the forward-only analysis does not survive reverse typing — every
single inbound edge to P3, including the unanimous 4-operator one, reclassifies as
DEVELOP.** Under this test, P3 looks like a generic attractor (a page that reads as a
plausible "productive development" from almost anything), not a hub with a genuinely
varied relational profile. P1, despite being majority-DEVELOP too, is the more
structurally interesting of the two attractors, because it's the only one with any
surviving non-DEVELOP signal at all.

## 5. Forward confidence vs. reverse recovery (singletons, n=34)

Recovered (n=8): mean forward confidence 0.458. Not recovered (n=26): mean forward
confidence 0.301. There is a positive difference in the means, but the relationship is
noisy, not a clean separating threshold — e.g. the highest-forward-confidence pair (0.96)
was recovered, but several mid-range pairs (0.51-0.59) were not, and one low pair (0.16)
was recovered while most other low pairs were not. Treating this only as an observed
association, not a calibrated probability: **higher forward confidence is weakly
associated with successful reverse recovery, but is not a reliable predictor on its own**
in this sample.

## 6. BRIDGE diagnostic

* Singleton BRIDGE recovery rate: **0/11 (0%)**.
* What BRIDGE edges are misclassified as: **100% DEVELOP** (11/11) — no other operator
  ever appears as the reclassification.
* Reverse confidence for these 11 reclassified-as-DEVELOP pairs: 0.88, 0.80, 0.53, 0.76,
  0.20, 0.50, 0.62, 0.72, 0.61, 0.56, 0.69 — mean 0.625. The model isn't hedging when it
  overrides BRIDGE with DEVELOP; on average it's fairly confident in the DEVELOP relabel.

Combined with the field-wide finding that BRIDGE already had the lowest forward confidence
of any operator (7 of 11 bottom-decile picks), this reverse-typing result is a second,
independent line of evidence pointing the same direction: **as currently worded, BRIDGE
does not behave like a distinct, independently recoverable relation from DEVELOP's
perspective.** Not rewritten here, per instruction.

## 7. NONE

0 of 53 reverse classifications selected NONE.

## Open threads for a next, explicitly scoped experiment

* Whether DEVELOP's dominance is about its wording specifically (too permissive) or about
  asymmetry in the classification task itself (state includes both full passages, which
  may just read as "these two things go together, therefore develops") is not yet
  separated.
* CONTRADICT's partial signal (3/12 singleton, concentrated at P1) and ECHO's weak signal
  (1/7) haven't been diagnosed the way BRIDGE has (no dedicated collision/confidence
  breakdown for them individually yet).
* No shuffled or repeated reverse-typing runs have been done — this is one classification
  per pair, canonical framing only, matching the same "Phase 1, no duplicates yet" scoping
  the reader set for this run.
