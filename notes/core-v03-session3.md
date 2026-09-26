# Core v0.3 — session 3 handoff (2026-09-25)

Executable scores on branch `atlas-memory-exploration`, continuing from `6e7221c`
(session 2). This note is the handoff. Session 1/2 records in
`notes/core-v03-status.md` stay historical. No provider call was made for this
completion pass. Brennan's reader on `127.0.0.1:8765` and his live stores were not
modified by the verification below.

## What Brennan can try

Isolated preview: **http://127.0.0.1:8773/**

The literary reader on port 8765 is a separate process. Use 8773 for the demonstration.

1. Click **Try outward and return**. The page is the synthetic starting room (RX1),
   labelled separately from the 41-page corpus. Progress reads **Outward — visit two
   new passages · 0 of 2**.
2. **Follow** RX3, then click **ECHO**. RX5 and RX7 are offered. RX1 is excluded:
   "Already visited on this journey; choose a passage you have not visited yet."
   Previous / Next do not move the reader.
3. **Follow** RX5, then click **ECHO**. Only RX1 is offered. **Follow** RX1. Progress
   reads **Complete — you returned to the starting passage.**
4. Open the journey link (`/journey?session_id=…`). It shows the pinned score,
   four arrivals, and the return spacing: candidate arrival index 3, index distance 3,
   two intervening encounters.
5. **Leave demonstration** restores the literary journey and keeps an inspect link
   to the synthetic performance.

**Try neutral choices** is the comparison: from RX3, ECHO still offers an immediate
return to RX1, and the page list can move.

## Implemented behavior and changed contracts

New sessions pin a validated `score/1` configuration (`scores.neutral_score()` unless
a demonstration passes `recurrence_fixture`). `score-resolver/1` applies groundedness,
source match, field policy, and support floor, then score guards, and only then the
display limit and rank. A valid return is not dropped because a limit ran first.
Hard failures stay out of the ranked list.

Movement counters advance only inside `scores.progress`, and only for a successful
committed action named in that movement's `advance_on`. The recurrence fixture counts
Q arrivals only. Rejected actions, identical retries, refresh, and pause/resume do
not advance it. Pause and resume still bump the revision, so earlier offer sets become
stale. Dedup still runs before the stale-revision check. A reused request id with a
different payload is `request_id_reused`.

Return spacing is computed for the candidate arrival index `len(H)`, not the current
index. Index distance is `arrival - previous`. Intervening encounters are that
distance minus one. The completed RX1→RX3→RX5→RX1 route records arrival index 3,
distance 3, intervening 2.

Relocations go through the same score policy before a destination is adopted:
Previous, Next, page list, in-app Back, browser history, and "Continue here".
During recurrence they are rejected (`relocation_forbidden`) and create no encounter.
Legacy research follows stay labelled as research. On the synthetic field, and while
relocation is forbidden, those routes return 409 and do not relocate. Neutral
literary Q and manual relocation stay available; only Q advances the neutral counter.

Endings stay distinct: `blocked` (no eligible choice, rules unchanged), `paused`,
`ended_by_reader`, `exited`, and `complete`. **Leave demonstration** is `exit` and
can resume the previous literary session. **End this performance** is `end_journey`.
Completion is not rewritten into exit.

New journals retain the exact score snapshot, score hash, resolver inputs, candidate
rows, decision reasons, and the prose bytes needed to rebuild offers offline.
Historical journals without `score_contract` keep the original neutral placeholder
(`score_id`, `score_version`, `movement` only). They gain no fabricated score events.
`performance_ended` is the only new event type.

Bond wording remains `destination_opening_sentence`. Synthetic RX pages are not part
of the authored corpus and are not mirrored into the legacy reader stores.

## Verification in this completion pass

```
.venv/bin/python -m pytest -q -rs
```

**534 passed, 1 skipped** in 11.63s, after the journey-page wording fix and the
return-exclusion sentence below. The skip is
`tests/test_context.py:85`: the F12 sentence map is already reviewed, so the old
"not reviewed" blocker no longer applies. No other test skipped.

An earlier run of the same command failed one existing assertion,
`test_journey_page_never_posts`, because the journey hint had dropped the sentence
"no textual evidence span recorded". That sentence is restored in `journey.html`.
The assertion was not weakened. Decision replay of a scored journal uses retained
inputs, so a later change to the live options provider does not count as drift;
corrupting those retained inputs still fails replay (`tests/test_core_score_replay.py`).

Fresh browser observation on the isolated preview (Cursor browser, not the saved
Playwright run):

- Session `s_72814d0f6ca9` completed RX1 → RX3 → RX5 → RX1.
  Stored score: `recurrence_fixture`, counters `{outward: 2, return: 1}`, status
  `complete`. The return encounter is a literary bond, `is_return` true,
  `return_index_distance` 3, `intervening_encounters` 2.
- At RX1, revision 1, clicking **Next** left the API at RX1 / 1 encounter / counter 0.
- At RX3 ECHO the offer was RX5 and RX7. The stored RX1 decision is
  `target_already_visited`. The reader said "Already visited on this journey…"
- At RX5 ECHO the only offer was RX1. The stored spacing decision is
  `return_spacing_satisfied` with `candidate_arrival_index` 3, previous encounter 0,
  index distance 3, intervening 2, minimum 2.
- Journey inspection for that session showed `recurrence_fixture v1 · complete`,
  revision 4, 4 encounters, 8 journal events, and the pinned rules. Build line:
  `6e7221c66d (uncommitted changes)` at the time of the walk.
- A second walk, `s_a047249cb246`, confirmed the return list is only RX1 and that
  RX7 now reads "A return only applies to a passage already visited on this journey."
  **Leave demonstration** restored literary session `s_6627c5f16400` at P1.
- Preview provider counters stayed `contextual_dispatches: 0`,
  `single_pick_dispatches: 0`.

Fresh legacy replay, provider calls 0, bundle
`data/verification/core_v03_session2_demo_2026-09-25/journey_s_10169fa2df45.json`:

- Without `--legacy-atlas`: state replay ok (11 encounters, revision 11); decision
  replay **not** available (`legacy_bundle_missing_frozen_inputs` on both offer sets);
  retained content ok for the four encountered versions; score bundle compatibility
  `legacy-neutral`. Overall `ok: false`, with
  `recorded_historical_replay.ok: true`.
- With `--legacy-atlas`: decision replay ok under `legacy_supplied_atlas`. That uses
  the local atlas explicitly. The old bundle alone still does not contain every
  candidate input.

## Earlier evidence, not re-executed in this pass

These files were already in the working tree. Treat them as the interrupted session's
records, not as a new run:

- `data/verification/core_v03_session3_demo_2026-09-25/README.md` and final run
  `20260926T012138680016Z/report.json` (Playwright/Chrome, isolated store, outward
  and return, shortcut rejection, pause/restart, stale tab, legacy research 409s,
  distinct endings). Earlier timestamped runs in that folder are retained as
  intermediate failures and passes.
- `data/verification/core_v03_session3_neutral_2026-09-25/neutral_parity.json`:
  reports `ok: true`, 328 comparisons, 41 sources × 4 operators × 2 policies,
  `provider_calls: 0`. `history_dependence.json` reports the ordered-history checks
  including the intervening boundary.
- `data/verification/core_v03_session3_replay_2026-09-25/README.md`: reports 84
  focused tests and the four new bundles versus two historical bundles.

Python sources were not edited after the preview process started, except the two
static wording fixes above. Those files are read from disk on each request.

## Preview

| | |
| --- | --- |
| URL | http://127.0.0.1:8773/ |
| Process | PID 48459, started 2026-09-25 20:30:11 local (`2026-09-26T01:30:11Z`) |
| Command | `.venv/bin/python` (resolved to the Homebrew 3.12 framework binary) `tests/acceptance/serve_isolated.py /tmp/gibsey-core-v03-session3-preview-20260925 8773` |
| Storage | `/tmp/gibsey-core-v03-session3-preview-20260925` (not Brennan's `data/`) |
| Parent | Codex app-server PID 40657. It was already listening when this completion started. It was not restarted. |
| Stop | `kill 48459` only if that PID is still this command. Do not stop PID 85809 (`gibsey serve-reader` on 8765). |
| Restart | From the repo root, only when 8773 is free: `.venv/bin/python tests/acceptance/serve_isolated.py /tmp/gibsey-core-v03-session3-preview-20260925 8773` |

`/api/build` on 8773 reported revision `6e7221c66d06d689611a4af9e1aed82e33df9ab1`,
`dirty: true`. The score controls **Try neutral choices**, **Try outward and return**,
and **Leave demonstration** are in the served page.

## Remaining limitations

- Old Session 1/2 bundles do not replay decisions offline unless `--legacy-atlas` is
  passed. State replay of those journals does not invent score events.
- Firefox, Safari, and keyboard-only use were not run.
- Browser Forward is covered by the reader tests; this completion's browser walk did
  not press the browser Forward button.
- The 328-comparison parity file and the Playwright report were not regenerated after
  the two wording edits. The pytest suite was.
- Bond wording is still the destination opening sentence.
- The real literary route below is a proposal, not an executable score.

## Literary pilot question

**Awaiting Brennan's artistic review.** Not an approved score.

Should the first real recurrence pilot make the reader revisit "I didn't write this"
after the text has implicated the reader as an author, using P1→P5→F11→P1, with F5
as the more uncertain alternative?

Route, exact bond ids, assessment ids, fit/confidence, quoted spans, and the gaps
(closure bonds not yet published as retained offers; spans are not atlas evidence;
confidence below 0.5 on two edges) are in `notes/core-v03-literary-pilot.md`.
Decision evidence and the proposed textual reading are labelled separately there.

## Next bounded task

Wait for Brennan's approval or revision of that pilot. The next implementation is
that one reviewed real score on the existing corpus, with the same guard, replay,
and exit rules. Do not start the matrix inspector, DSPy, or A/L generation first.
