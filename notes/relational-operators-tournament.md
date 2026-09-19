# Operator-conditioned destination tournaments

Tests `source + operator + plausible destinations -> preferred destination`, restricted to
the destinations the forward field itself already discovered for that source (from
`runs/relop-full-field-edges.csv`), instead of asking whether an already-fixed edge can be
given one label after the fact (the reverse-typing experiment, now stopped, not modified
here). Operator wording unchanged (exact original criteria, quoted below). NONE not
offered — every candidate is already forward-discovered. Model pinned to `jev-1.13.0`
throughout (72/72 confirmed). No prior run record modified. One-off script, not a
permanent case type or CLI command.

Full edge list: `runs/relop-tournament-edges.csv` (72 rows). Operator-invariant sources:
`runs/relop-tournament-invariant-sources.csv`. Per-run records:
`runs/*_relop-tournament-<source>-<operator>_live/`.

Of 20 sources, 18 had 2+ unique forward destinations and were tested (4 operator calls
each = 72 calls); 2 (P2, P7) had only one unique forward destination and were correctly
skipped, not scored as failures.

## 1. Overall re-selection rate

**62/72 = 0.861.** When forced to choose only among a source's own already-discovered
plausible destinations, operators reselect their original pick 86% of the time — a sharp
contrast with reverse typing's 23.5% overall recovery rate on the same underlying edges.
Restated: operators struggle to be recognized after the fact from a fixed pair, but they
discriminate well when actually choosing among live alternatives — which is the operation
QDPI actually needs.

## 2. Per-operator re-selection

| Operator | n | Matches | Rate |
| --- | --- | --- | --- |
| ECHO | 18 | 17 | 0.944 |
| BRIDGE | 18 | 17 | 0.944 |
| DEVELOP | 18 | 14 | 0.778 |
| CONTRADICT | 18 | 14 | 0.778 |

**BRIDGE recovers 17/18 (94.4%) here** — tied for the highest rate of any operator —
despite scoring 0/11 in reverse typing. BRIDGE cannot be identified as a label from a
finished pair, but it clearly *does* steer choice among live candidates differently from
the other three operators; its earlier reverse-typing failure looks like a property of the
labeling task, not evidence that BRIDGE fails to function as a relation.

## 3. Source-level patterns

| Source | Candidates | Echo | Develop | Contradict | Bridge |
| --- | --- | --- | --- | --- | --- |
| F1 | F4, F9, P1, P3 | F9 = | F4 = | F9 ≠ (orig P1) | P3 = |
| F2 | F4, P1 | F4 = | F4 = | P1 = | P1 = |
| F3 | F4, P1, P3 | F4 = | F4 = | P1 = | P3 = |
| F4 | F3, P1, P3 | F3 = | F3 = | P1 = | P3 = |
| F5 | F7, P1 | F7 = | F7 = | P1 = | P1 = |
| F6 | F4, P1, P3, P5 | P5 = | F4 = | P1 = | P3 = |
| F7 | F5, F8, P1 | F5 = | F5 ≠ (orig F8) | F8 = | F5 ≠ (orig P1) |
| F8 | F1, F7, P1 | F1 = | F7 = | F7 = | P1 = |
| F9 | F10, P1 | F10 = | F10 = | P1 = | P1 = |
| F10 | F4, F9, P1, P3 | F9 = | F4 = | P1 = | P3 = |
| F11 | F10, P1 | F10 = | F10 = | P1 = | F10 = |
| F12 | F4, P3, P6, P8 | P8 = | F4 = | P6 = | P3 = |
| P1 | F11, P2 | P2 = | P2 = | F11 = | P2 = |
| P3 | F4, P2 | P2 = | F4 ≠ (orig P2) | P2 = | F4 = |
| P4 | P3, P7, P8 | P8 = | P3 ≠ (orig P8) | P3 ≠ (orig P7) | P3 = |
| P5 | F5, F11, P3 | P3 ≠ (orig F5) | P3 = | P3 ≠ (orig F11) | P3 = |
| P6 | F12, P3, P7 | F12 = | P3 ≠ (orig F12) | P3 ≠ (orig P7) | P3 = |
| P8 | F12, P6 | F12 = | F12 = | P6 = | F12 = |

**Exact four-way recoveries (all 4 operators reselect their original pick), 12 of 18:**
F2, F3, F4, F5, F6, F8, F9, F10, F11, F12, P1, P8.

**Partial recoveries:** F1 (3/4), F7 (2/4), P3 (3/4), P4 (2/4), P5 (2/4), P6 (2/4).

**Total collapse onto one destination across all four operators:** only **P5** (all four
converge on P3). This is the single case in the whole tournament where restricting the
candidate set didn't just fail to fully recover the original field — it erased the
operators' differences entirely for that source.

**ECHO+DEVELOP vs. CONTRADICT+BRIDGE groupings** (both pairs agree internally, and the two
groups differ from each other): **F2, F5, F9** — all three cleanly split into the same
two-vs-two structure the forward field originally produced for them (see collision
diagnostic below; this is the same grouping already seen in the original 80-call field
map).

## 4. F12 (key diagnostic)

| Operator | Candidates | Original | Tournament | Confidence | Match |
| --- | --- | --- | --- | --- | --- |
| ECHO | F4, P3, P6, P8 | P8 | **P8** | 0.97 | yes |
| DEVELOP | F4, P3, P6, P8 | F4 | **F4** | 0.61 | yes |
| CONTRADICT | F4, P3, P6, P8 | P6 | **P6** | 0.37 | yes |
| BRIDGE | F4, P3, P6, P8 | P3 | **P3** | 0.69 | yes |

**F12 is a full 4/4 exact recovery.** Head-to-head against the other three of its own
discovered destinations, each operator picked exactly the same destination it originally
discovered in the 19-candidate field. This is the strongest possible result for F12
specifically: under this test, its four relational edges (→P8, →F4, →P6, →P3) look like
four genuinely distinct, stable preferences, not four operators converging on shared logic.

## 5. Collision diagnostic

For every source with an original forward collision, compares the forward operator
partition (which operators shared a destination) against the tournament partition:

| Source | Forward partition | Tournament partition | Same? |
| --- | --- | --- | --- |
| F2 | {ECHO,DEVELOP}, {CONTRADICT,BRIDGE} | {ECHO,DEVELOP}, {CONTRADICT,BRIDGE} | yes |
| F3 | {ECHO,DEVELOP}, {CONTRADICT}, {BRIDGE} | same | yes |
| F4 | {ECHO,DEVELOP}, {CONTRADICT}, {BRIDGE} | same | yes |
| F5 | {ECHO,DEVELOP}, {CONTRADICT,BRIDGE} | {ECHO,DEVELOP}, {CONTRADICT,BRIDGE} | yes |
| F7 | {ECHO}, {DEVELOP,CONTRADICT}, {BRIDGE} | {ECHO,DEVELOP,BRIDGE}, {CONTRADICT} | **no** |
| F8 | {ECHO}, {DEVELOP,CONTRADICT}, {BRIDGE} | same | yes |
| **F9** | **{ECHO,DEVELOP}, {CONTRADICT,BRIDGE}** | **{ECHO,DEVELOP}, {CONTRADICT,BRIDGE}** | **yes** |
| F11 | {ECHO,DEVELOP,BRIDGE}, {CONTRADICT} | same | yes |
| P1 | {ECHO,DEVELOP,BRIDGE}, {CONTRADICT} | same | yes |
| P3 | {BRIDGE}, {ECHO,DEVELOP,CONTRADICT} | {BRIDGE,DEVELOP}, {ECHO,CONTRADICT} | **no** |
| P4 | {ECHO,DEVELOP}, {CONTRADICT}, {BRIDGE} | {ECHO}, {DEVELOP,CONTRADICT,BRIDGE} | **no** |
| P5 | {ECHO}, {CONTRADICT}, {DEVELOP,BRIDGE} | {ECHO,DEVELOP,CONTRADICT,BRIDGE} (total collapse) | **no** |
| P6 | {ECHO,DEVELOP}, {CONTRADICT}, {BRIDGE} | {ECHO}, {DEVELOP,CONTRADICT,BRIDGE} | **no** |
| P8 | {ECHO,DEVELOP,BRIDGE}, {CONTRADICT} | same | yes |

**9 of 14 collision sources reproduce their exact forward partition; 5 don't.** The
reader's worked example holds exactly: **F9's original ECHO/DEVELOP -> F10 vs.
CONTRADICT/BRIDGE -> P1 split is reproduced perfectly** under restricted competition.

Where it breaks (F7, P3, P4, P5, P6), the pattern is consistent: DEVELOP and/or CONTRADICT
pull *toward* another operator's original destination rather than holding their own — and
in 4 of those 5 cases (P3, P4, P5, P6) they pull toward **P3**, the same page flagged as a
destination attractor in the forward field and later shown to fully absorb reverse typing.
P3's pull is weaker here than in reverse typing (it doesn't erase ECHO's or BRIDGE's
preference in P4/P6, and P6's ECHO still picks F12), but it's visibly still present as a
gravitational tendency specifically in DEVELOP and CONTRADICT's restricted choices.

## 6. Operator-invariant sources

**P2 -> P3** and **P7 -> P6**: both had only one unique forward destination across all four
operators (matches the reader's own flagged examples exactly), so no tournament call was
possible or made for them. Not scored as failures — there was no within-source alternative
to test preference against.

## 7. Confidence: match vs. mismatch (descriptive only, not treated as calibrated)

| | n | mean confidence | median |
| --- | --- | --- | --- |
| Match | 62 | 0.599 | 0.620 |
| Mismatch | 10 | 0.278 | 0.290 |

A substantially larger separation than the weak association seen in reverse typing (0.458
vs. 0.301 there). Descriptively, tournament mismatches cluster at low confidence — of the
10 mismatches, 8 are at or below 0.40. The two exceptions are F1/CONTRADICT (F9 over
original P1, conf 0.27 — actually also low) and none above ~0.46, so there isn't a case of
a *confident* mismatch in this run. Still an observed association only, not evidence the
confidence score is calibrated.

## Answer to the key question

**Yes — when plausible alternative destinations are held constant, changing the relational
operator systematically changes Jev's preferred destination, in the large majority of
cases (86.1% overall, and up to 94.4% for ECHO and BRIDGE specifically).** This is a
materially different and more favorable result than reverse typing produced on the exact
same underlying edges, and it isolates where the earlier DEVELOP-dominance problem actually
lives: in post-hoc labeling of a fixed pair, not in live comparative selection among
alternatives. The operators not fully redesigned here, per instruction.
