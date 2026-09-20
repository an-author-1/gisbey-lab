# Holdout replication, Phase B: operator-conditioned tournament

Restricted-candidate tournament on the holdout corpus (LF1-16, PR1-5), using each source's
own forward-discovered unique destinations from Phase A
(`runs/relop-holdout-full-field-edges.csv`). Frozen v0.1 operator wording unchanged, no
NONE option, pinned `jev-1.13.0` (80/80 confirmed). No prior run record modified — training
corpus, its edge CSVs, and `notes/q-operator-prototype-v0.1.md` untouched.

20 of 21 sources had 2+ unique forward destinations and were tested; **LF4** was
operator-invariant (all four operators -> LF3 already in Phase A) and correctly skipped.

Edge list: `runs/relop-holdout-tournament-edges.csv`. Invariant sources:
`runs/relop-holdout-tournament-invariant-sources.csv`. Per-run records:
`runs/*_relop-holdout-tournament-<source>-<operator>_live/`.

## 1. Overall tournament re-selection rate

**63/80 = 0.787.**

## 2. Re-selection rate by operator

| Operator | n | Matches | Rate |
| --- | --- | --- | --- |
| CONTRADICT | 20 | 20 | 1.000 |
| DEVELOP | 20 | 18 | 0.900 |
| ECHO | 20 | 13 | 0.650 |
| BRIDGE | 20 | 12 | 0.600 |

**CONTRADICT's 100% needs a caveat, not a celebration**: 13 of its 20 targets were already
LF3 (the dominant attractor, see #7), so this rate is substantially inflated by one page
being an easy, near-automatic answer rather than by CONTRADICT discriminating well in
general. **ECHO and BRIDGE both dropped sharply** from the original field's 0.944 each to
0.650 and 0.600 — this is the clearest regression in the holdout run.

## 3. Exact 4/4 source recoveries

**7 of 20 (35.0%): LF3, LF7, LF8, LF11, LF12, PR1, PR3.**

## 4. Partial recoveries

13 sources at 2 or 3 of 4 matches: LF1 (3), LF2 (3), LF5 (2), LF6 (3), LF9 (3), LF10 (2),
LF13 (2), LF14 (3), LF15 (3), LF16 (2), PR2 (3), PR4 (3), PR5 (3). **No source scored 0 or
1** — every tested source recovered at least half its original operators, even where it
missed the exact 4/4 bar.

## 5. Operator-invariant sources

**LF4 -> LF3** (all four operators). Not scored as a failure, per instruction — no
within-source alternative existed to test preference against.

## 6. Collision patterns

Of the 11 sources with an original forward collision, **5 of 11 (45.5%) reproduce their
exact partition**: LF8, LF11, LF12, PR1, PR3. The other 6 (LF1, LF2, LF5, LF15, PR2, PR4)
don't — in every one of those 6 cases, the mismatch pulls toward **LF3 or LF11**, the two
dominant attractors (see #7), not toward an arbitrary third destination.

## 7. Destination attractors (tournament selections)

| Destination | Count (of 80) |
| --- | --- |
| LF3 | 23 |
| LF11 | 19 |
| LF6 | 8 |
| PR1 | 8 |
| PR2 | 4 |
| LF7, LF8, PR3 | 3 each |
| LF16, PR4 | 2 each |

Mean 5.33/destination, stdev 6.57. **Both LF3 (23) and LF11 (19) sit well above mean +
2*stdev (~18.5)** — two simultaneous strong attractors, compared to the training corpus's
single dominant pair (P1, P3, 14/80 each in the original tournament). Unlike the training
corpus, where the forward-field attractor (P3) only partially carried its pull into
restricted tournament competition, **here LF3 and LF11 dominate even head-to-head
comparison against a small, source-specific candidate set** — a stronger and more
persistent version of the same phenomenon.

## 8. Confidence: matches vs. mismatches

| | n | mean | median |
| --- | --- | --- | --- |
| Match | 63 | 0.600 | 0.650 |
| Mismatch | 17 | 0.315 | 0.300 |

Nearly identical separation to the original tournament (0.599 vs. 0.278) — descriptive
only, not treated as calibrated.

## 9. Factual comparison against the original field

| Metric | Original (training corpus) | Holdout (LF/PR) |
| --- | --- | --- |
| Overall tournament re-selection | 62/72 = 86.1% | 63/80 = 78.7% |
| Exact 4/4 source recovery | 12/18 = 66.7% | 7/20 = 35.0% |
| ECHO | 17/18 = 94.4% | 13/20 = 65.0% |
| DEVELOP | 14/18 = 77.8% | 18/20 = 90.0% |
| CONTRADICT | 14/18 = 77.8% | 20/20 = 100.0% (attractor-inflated, see #2) |
| BRIDGE | 17/18 = 94.4% | 12/20 = 60.0% |

Every metric moved. Two operators (DEVELOP, CONTRADICT) went *up*; two (ECHO, BRIDGE) went
*down*, and by a wide margin. The overall rate held up reasonably well (a 7.4-point drop)
but the exact-4/4 recovery rate — the strictest, most demanding metric — nearly halved
(66.7% -> 35.0%).

## Answer to the experimental question

**Does operator-conditioned destination selection reproduce on unseen Gibsey material
strongly enough to justify promoting Q Operator Prototype v0.1 into the QDPI
implementation? Not yet, on this evidence.**

The result is genuinely mixed, not a clean pass or fail. In favor: the overall
re-selection rate stayed well above chance (78.7%, vs. what would be roughly 33-50% for
random choice among 2-4 candidates), no source scored 0 or 1 matches, and the
match/mismatch confidence separation replicated almost exactly. That's real evidence the
operators are doing *something* systematic on genuinely unseen material, not producing
noise.

Against promotion: the exact-4/4 recovery rate — the measure closest to "this operator
reliably produces its own distinct destination" — fell by half. ECHO and BRIDGE, two of
the two strongest operators in the original field, both dropped by roughly 30 points.
CONTRADICT's apparent perfect score is substantially explained by one attractor page (LF3)
rather than general discriminative strength. And a second, stronger destination-attractor
problem (LF3 and LF11 both dominating even restricted competition) shows up here that
wasn't as pronounced in the training corpus's tournament phase specifically.

This reads as **partial replication with operator-specific and attractor-specific
weaknesses**, not a clean confirmation. The honest recommendation is to treat v0.1 as
*not yet* ready for promotion into the QDPI implementation, and to run targeted diagnostics
on (a) why ECHO and BRIDGE specifically regressed, and (b) what makes LF3 and LF11 pull so
strongly even under restricted comparison — the same kind of dedicated diagnostic already
done for BRIDGE on the training corpus — before deciding whether the wording needs to
change (a decision explicitly out of scope for this experiment) or whether the field
itself needs different assembly. Operators were not modified here, per instruction, even
though holdout performance fell on two of the four.
