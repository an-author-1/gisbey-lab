# Relational operators diagnostic follow-up

Follow-up to `notes/relational-operators-experiment.md`. Operator wording is unchanged
(same ECHO/DEVELOP/BRIDGE criteria, quoted there verbatim). No existing run records were
altered. Reuses the same context/adapter/validator/recorder/runner components, again as a
one-off script, not a permanent case type or CLI command.

**Model pinning:** `jev-1.13.0` (the exact version both prior experiments returned) was
requested explicitly instead of the `jev-latest` alias, and accepted by the API on the
first call. All 12 diagnostic runs below used the pinned version, confirmed via each run's
own `returned_model`.

**Infrastructure note (not fixed here, per "reuse existing infra unchanged"):** one run
crashed on a directory collision — `recorder.record_run`'s run id is
`<UTC-second timestamp>_<case_id>_<mode>`, and two calls with the same `case_id` completing
within the same second produce an identical directory name. Worked around at the script
level by suffixing `case_id` with the order label per call; the 5 runs completed before the
crash were kept (verified against their saved `response.json`) rather than re-run. Flagging
this as a real latent bug in the shared recorder for a future (non-diagnostic) fix.

## Experiment A: ECHO/DEVELOP collision probe

### F9, with F10 removed from candidates (18 candidates + NONE)

| Operator | Order | Destination | Confidence |
| --- | --- | --- | --- |
| ECHO | natural | F1 | 0.71 |
| ECHO | shuffled | F1 | 0.73 |
| DEVELOP | natural | F1 | 0.22 |
| DEVELOP | shuffled | F1 | 0.18 |

Both operators converge on a *new* shared destination (F1) once F10 is removed. This did
not separate them — it shows the overlap goes at least one layer deep for F9: it isn't
only that ECHO and DEVELOP happened to share a single top pick (F10); with that pick gone,
they immediately agree on the next one too.

### F3, with F4 removed from candidates (18 candidates + NONE)

| Operator | Order | Destination | Confidence |
| --- | --- | --- | --- |
| ECHO | natural | F2 | 0.49 |
| ECHO | shuffled | F2 | 0.33 |
| DEVELOP | natural | P3 | 0.23 |
| DEVELOP | shuffled | P3 | 0.41 |

Here the operators separate cleanly once F4 is removed: ECHO moves to F2, DEVELOP moves to
P3, consistently across both orders. For F3, the original ECHO/DEVELOP collision on F4
looks like a shared top pick sitting on top of genuinely different secondary preferences —
the opposite pattern from F9.

All 8 Experiment A pairs were stable across both candidate orders (no reordering effect).

## Experiment B: F9 BRIDGE ambiguity probe

Four additional F9 → BRIDGE runs, full original candidate set (19 + NONE), each
independently shuffled, pinned model:

| Run | Destination | Confidence |
| --- | --- | --- |
| shuffled-1 | P3 | 0.26 |
| shuffled-2 | P3 | 0.29 |
| shuffled-3 | P3 | 0.24 |
| shuffled-4 | P2 | 0.12 |

### Combined distribution across all six known F9 → BRIDGE runs

| Run | Order | Destination | Confidence |
| --- | --- | --- | --- |
| original experiment | natural | P1 | 0.13 |
| original experiment | shuffled | P3 | 0.26 |
| diagnostic | shuffled-1 | P3 | 0.26 |
| diagnostic | shuffled-2 | P3 | 0.29 |
| diagnostic | shuffled-3 | P3 | 0.24 |
| diagnostic | shuffled-4 | P2 | 0.12 |

**P3: 4/6. P1: 1/6 (only the single natural-order run). P2: 1/6.** P3 is the destination
that recurs across independently shuffled orders; P1 appeared exactly once, on the one run
that used the corpus's natural (unshuffled) order, and hasn't recurred under any of five
shuffles. Confidence stayed low throughout (0.12-0.29) — this remains the lowest-confidence
operator observed in either experiment, and the destination landscape looks like it has a
plurality favorite (P3) rather than one dominant answer or true multi-way ambiguity.

## Run directories

`runs/20260919T221234Z_relop-diag-F9-echo-noF10_live/`,
`runs/20260919T221235Z_relop-diag-F9-echo-noF10_live/`,
`runs/20260919T221235Z_relop-diag-F9-develop-noF10_live/`,
`runs/20260919T221236Z_relop-diag-F9-develop-noF10_live/`,
`runs/20260919T221237Z_relop-diag-F3-echo-noF4_live/`,
`runs/20260919T223747Z_relop-diag-F3-develop-noF4-natural_live/`,
`runs/20260919T223747Z_relop-diag-F3-echo-noF4-shuffled-b_live/`,
`runs/20260919T223748Z_relop-diag-F3-develop-noF4-shuffled-b_live/`,
`runs/20260919T223748Z_relop-diag-F9-bridge-extra1-shuffled-1_live/`,
`runs/20260919T223749Z_relop-diag-F9-bridge-extra2-shuffled-2_live/`,
`runs/20260919T223749Z_relop-diag-F9-bridge-extra3-shuffled-3_live/`,
`runs/20260919T223750Z_relop-diag-F9-bridge-extra4-shuffled-4_live/`
