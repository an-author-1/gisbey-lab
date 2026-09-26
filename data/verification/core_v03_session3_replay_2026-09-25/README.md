# Session 3 replay evidence — 2026-09-25

These are isolated engineering fixtures, not Brennan's journeys. `replay_result.json`
contains API/replay observations only; the separate browser evidence owns browser claims.

Reproduce from the repository root:

```sh
.venv/bin/python data/verification/core_v03_session3_replay_2026-09-25/run_evidence.py
.venv/bin/python -m pytest -q tests/test_core_score_replay.py tests/test_core_transactions.py tests/test_core_scores.py
```

Observed: **84 tests passed**. The script passed with socket connection attempts disabled,
zero provider calls, two historical bundles, two live historical journals, and four
new bundles. SHA-256 comparisons confirm all four historical input files remain unchanged.

- Session 1 and Session 2 original exports reproduce state and decisions using an
  **explicitly supplied local frozen atlas**. Those older bundles do not contain every
  candidate needed for standalone decision reconstruction. Calling `replay_bundle`
  without `legacy_core` reports that unavailable dependency; it does not fabricate it.
- Session 1 comparison normalizes only absent non-manual encounter `cause=None` and
  Q request `kind="action"` fields, reporting both compatibility codes. Existing score
  state remains the historical neutral placeholder; no historical score events appear.
- The live read-only sessions `s_8e87959b8046` and `s_d09a7820e595` pass; they have zero
  and five offer sets respectively. Relocations require no invented offer.
- `session3_recurrence_replay`: an empty CONTRADICT offer records blockage at zero
  progress; pause/resume leaves movement counts unchanged; RX1 → RX3 → RX5 → RX1
  completes with counters `{outward: 2, return: 1}`. The retained return guard cites
  encounter 0, candidate arrival 3, index distance 3, and **two intervening encounters**.
- `session3_neutral_replay`: immediate return remains offered at RX3, and manual
  relocation to RX1 records an arrival with no bond or operator.
- Separate `end_journey` and `exit` bundles retain distinct outcomes.

New bundles replay from retained bytes with candidate providers disabled, including
ordered eligibility reasons, final state, every recorded state checkpoint, score
configuration fingerprints, resolver/reducer versions, and content hashes. Their
journals are also retained under `core/`. Tests intentionally damage score snapshots,
progress, frozen candidates, reasons, trace, manifests, and prose; replay rejects each.
