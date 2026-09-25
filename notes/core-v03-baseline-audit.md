# Core v0.3 baseline audit (2026-09-25, session 1)

Everything under "Observed" was read from the checkout or produced by the named read-only
scripts; nothing under it is proposed architecture. Investigations were run by three
read-only subagents (corpus/atlas, reader/persistence, composition/inspector) plus the
lead's own trace of the transition path; their scratch scripts are noted where results
depend on them. No provider call was made in this session.

## Observed baseline

- Branch `atlas-memory-exploration`, commit `f5847b0`, tree clean apart from the untracked
  `Gibsey_Core_v0.3_Weekend_Plan.md`. Startup: `.venv/bin/gibsey serve-reader` → reader on
  127.0.0.1:8765 (PID 50122, started 2026-09-21, serving `f5847b0`, `app.js` 51f4f768…).
  Tests at start: 372 passed, 1 skipped.
- Corpus: 41 pages, all identities confirmed. A content version is the sha256 of the
  file text (`corpus.py:49-51`); there is no version field. `data/corpus_manifest.json`
  covers only the 20 P/F pages (hashes correct) — not a 41-page manifest.
- Atlas (`data/atlas/assessments.jsonl`): 1,648 records, all `ok`, all live; every record's
  endpoint hashes equal the current vault and every embedded `state` text re-hashes to
  its recorded hash (0 mismatches). Under the active frozen config
  (`cfg-5a7766c6c2012139e7bab61f`, rubric v2, jev-1.13.0) every off-diagonal pair is
  assessed once: 1,640 complete, 0 unassessed / stale / failed. The 8 extra records are
  the rubric-v1 pilot and are not pooled. No pair has more than one compatible record.
- **164-cell inventory** (`data/verification/coverage_164_cells_2026-09-25.csv`, one row
  per page × operator; "supported" = score_norm ≥ 2/3 on the operator's dimension;
  "weak" = assessed below that floor, a value not a gap). Cells with ≥1 / ≥2 / ≥3 / 0
  supported and Discovery-eligible targets:
  ECHO 41/40/39/0 · DEVELOP 41/39/38/0 · BRIDGE 41/41/40/0 · **CONTRADICT 8/4/2/33**.
  Supported edges in total (incl. neighbors): ECHO 476, DEVELOP 569, CONTRADICT 20,
  BRIDGE 723. Discovery excludes 74 target pairs per operator. Published bonds exist in 3
  cells only (PR1×DEVELOP 3, PR4×BRIDGE 1, P1×CONTRADICT 1). The plan's target of two
  qualified destinations per operator is met for ECHO/DEVELOP/BRIDGE on ≥39 pages and
  **not met for CONTRADICT on 37 pages** — visible work, not a build defect.
- Layer-2 Choice runs: 466 loadable (413 destination, 53 reverse typing, 6 abstentions,
  0 errors), all endpoint hashes current; labeled `field_relative_choice`; imported by
  `atlas-inspect` only. Nothing in selection or state reads them.
- Real journey (untouched): 5 bonds, 6 `Q_follow` entries, 49 session-log events. Only
  the 2026-09-21 bond (P1→P6 CONTRADICT) carries endpoint hashes; the four legacy bonds
  validate through their run's `corpus_hashes`. Grounding on the claimed operator:
  PR1→PR4 DEVELOP supported (0.93); PR1→PR2 DEVELOP supported but not Discovery-eligible
  (authored neighbor); PR4→PR2 BRIDGE weak (0.34); P1→P6 CONTRADICT weak (0.23). Two
  legacy `from_page` values are wrong (the stale-active_page bug fixed on 09-20), left as
  recorded.
- **Reported P-page failure: does not reproduce.** Browser (Playwright/Chrome, isolated
  instance, build f5847b0): P1 DEVELOP shows 5 supported rows (P5 2.75, F11 2.54, LF6 2.5,
  F5 2.26, P8 2.07); P6 DEVELOP 5 supported; PR4 CONTRADICT LF14 supported + 2
  exploratory; 0 provider dispatches, no console errors. The abstaining single-winner
  path survives only behind "Ask Jev for a single pick (research)".
- Persistence today: a follow writes `proposals.json`, session-log line, `bonds.json`,
  `proposals.json` again, session-log line, `reader_state.json`, three session-log lines —
  per-file atomic only, one process-wide thread lock, no file locks, no state revision,
  no session identity (one global `reader_state.json`). `follow_token` dedup runs before
  validation but silently returns the earlier result for a reused token with a different
  payload (API-verified). Refresh, server restart and a new browser context each add one
  raw `page_viewed via=reload` line; derived encounters did not duplicate. No restart
  test existed. Tests covering dedup/validation: `test_state.py:134,186-208`,
  `test_reader_options.py:268-325,575,608`.
- Inspection today: raw `reader_state` JSON panel, option Details (current list only),
  `/api/atlas/profiles`, `/demo/pr2`, `atlas-inspect`; `session_review.py` skips follows
  without a run dir, so every operator-option follow is invisible to it. No textual
  evidence spans exist in any record.
- Analysis tooling: none for projections/composition; numpy absent; `atlas.api._classify`
  is the existing "latest ok record per pair under the active config" rule; `Field.all_ids()`
  and `api.all_pairs` iterate prefixes alphabetically (F, LF, P, PR) — not a stable manifest.

## Mapping to v0.3 contracts

See `notes/core-v03-contracts.md` (component table: reusable / extend / missing).

## Grounded route chosen for the persistent-Q demonstration

P1@c8adbba7f4ed →DEVELOP→ P5@23fc2364ab4a (assessment as-cc43d39d…): development 2.75/3
(norm 0.92), confidence 0.75, echo 2.97, direct_q_fit 2.81, redundancy 0.22; Discovery-
eligible. Agent reading (not a human judgment): P1 poses the unlocated author — "the
identity of The Author—the original author—has yet to be definitively located"; P5 turns
that into a suspect, "whom I suspect may, in fact, be The Author of these very pages".
Alternatives: P6→DEVELOP→PR3 (0.90, cross-text); P8→ECHO→F12 (0.99, a verbatim shared
sentence — strongest quote existence, weakest relation validity).
