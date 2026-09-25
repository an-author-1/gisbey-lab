# Core v0.3 — session 1 status (2026-09-25)

For a fresh Claude Code session. Read with `notes/core-v03-contracts.md` (contracts,
ownership) and `notes/core-v03-baseline-audit.md` (what was observed before any change).
Governing plan: `Gibsey_Core_v0.3_Weekend_Plan.md`. **The weekend milestone is not
complete**; this is the first slice.

Branch `atlas-memory-exploration`, commit **`1c0e8b4`** (from `f5847b0`). Reader on
127.0.0.1:8765 serves it (`/api/build`). Tests: 434 passed, 1 skipped (was 372). No
provider call was made in this session; no DSPy was installed.

## Acceptance status (plan §11 rows relevant to this slice)

| Check | Status | Evidence |
| --- | --- | --- |
| Corpus/import: 41 ids/hashes, originals retrievable | demonstrated | audit note; `data/atlas/index_manifest.json` rows; every atlas record's state text re-hashes |
| Atlas integrity: 164 cells accounted for; missingness vs weak vs error | demonstrated | `data/verification/coverage_164_cells_2026-09-25.csv`; 0 unassessed/stale/failed; CONTRADICT weak on 33 cells |
| Q execution: grounded bond, exact destination version | demonstrated (one route + 164 harness follows) | browser demo P1→DEVELOP→P5; acceptance reports 20260925T2154/2156Z |
| History: refresh/resume/retry add no encounters; reordered paths distinct; return spacing | demonstrated | `test_core_transactions.py`; browser demo (refresh, restart: 2 encounters, 3 journal events) |
| Concurrency: identical retry returns prior result; changed payload rejected; stale tab cannot move | demonstrated | `test_core_transactions.py`, `test_reader_core.py`; second-tab browser check |
| Recovery: restart preserves active version/history; post-arrival offer failure doesn't repeat arrival | demonstrated | restart scenario in the acceptance pass; options are a separate resolve, never a re-follow |
| Replay: provider-disabled per-event state equality and decision reconstruction | demonstrated | `gibsey core-replay`; demo bundle `data/verification/core_v03_demo_2026-09-25/` |
| Reader behavior: offered sentence followed | demonstrated with a caveat | the offered sentence is the destination's opening sentence (mechanical), not authored |
| Index/projection integrity | demonstrated | `test_analysis_manifest.py`, `test_analysis_projection.py`; manifest `man-3a78abbbfbe8e2a23d7e` |
| Operator composition (§4.8 fixture) | demonstrated — mathematical fixture check only | `test_analysis_composition.py`: ECHO→DEVELOP from A = {C via B}; DEVELOP→ECHO = {B via C}; counts = independent enumerator |
| Inspector evidence (cell → versioned text/status/bonds) | partial | `/journey` shows a recorded performance; no matrix/evidence/operator-order views yet |
| Score schema, eligibility under two histories, simulation parity, score-aware route inspection | not run | score interpreter deferred to session 2 |
| Literary grounding review | not run | no human judgment exists for any value; route readings are agent interpretation |
| DSPy optional | deferred | not installed; no isolated environment created |

## What exists now

- **Core** (`src/gibsey_lab/core/`): `identity` (version ids `P1@c8adbba7f4ed`, bond
  version ids hashed over both endpoint versions + operator + exact wording), `journal`
  (per-session append-only `data/core/sessions/<id>/events.jsonl`, one fsynced write per
  event, per-session `seq`, `revision_after`), `reducer` (pure; `H` ordered encounters
  with `return_index_distance` / `intervening_encounters`, `c`, `ell`, `r`), `core.Core`
  (`start_session`, `resume_session`, `resolve_options`, `execute_action`,
  `get_action_status`, `pause`, `unpause`, `acknowledge_presented`), `replay` (state +
  decision replay, journey bundle), `projectors` (mirrors committed events into the legacy
  `bonds.json` / `reader_state.json` / session log, idempotent per event seq, rebuildable),
  CLI `core-sessions`, `core-journey`, `core-replay [--export DIR]`, `core-start`,
  `core-options`, `core-execute`.
- **Reader**: operator buttons → `POST /api/core/options`; Follow → `POST /api/core/execute`
  with `expected_revision` and a per-click `request_id`; `GET/POST /api/core/session`,
  `/api/core/status`, `/api/core/pause|resume`; read-only `GET /api/core/journey` and the
  `/journey` page (exact prose, offer set with offered sentences, selection, decision
  evidence, state before/after; "no textual evidence span recorded" on every score).
  The old `/api/operator-options` and `/api/follow-option` remain routed but unused by the
  buttons; Refine still uses them.
- **Analysis** (`src/gibsey_lab/analysis/`): `index_manifest` (authored order, snapshot,
  `offset`/`decode`, staleness check), `projection` (M/S/A per operator, statuses
  preserved, policy not applied, `eligibility_mask` separate), `composition` (exact
  two-step counts, witnesses capped at 100 with exact totals, `route_id`,
  `compare_orders`), CLI `analysis-manifest`, `analysis-project`, `analysis-compose`.
  Outputs: `data/atlas/index_manifest.json`; `data/analysis/projection_man-3a78….json`
  (included edges ECHO 476, DEVELOP 569, CONTRADICT 20, BRIDGE 723; 0 duplicates
  collapsed); `compose_*` for ECHO,DEVELOP and DEVELOP,ECHO (E@D 7,435 walks over 1,488
  cells vs D@E 7,282 over 1,453; 1,339 cells differ) — **relation walks in a frozen
  projection, not score-valid navigation, not corpus truth.**

## Contracts fixed this session (for the later inspector / score / simulator)

- Version id, bond version id, offer set id, request fingerprint: `core/identity.py`.
- Event schema `core-event/1`, event types and which bump the revision: `core/journal.py`, `core/reducer.py`.
- Index manifest `index-manifest/1` with `manifest_id`, authored page order, operator
  order, snapshot (`atlas_config_id`, rubric, pinned model, `assessment_set_sha256`,
  `corpus_sha256`), `projection_rule: binary-projection-v1`, `support_floor 2/3`,
  `collapse_rule`. Status codes `included | assessed_below_floor | unassessed | stale |
  failed | self`. Witness `route_id` = hash(manifest id, projection rule, operator
  sequence, versions and assessment ids per step); label `kind: relation_walk`.
  `score_valid_simulation` and `recorded_reader_performance` are reserved labels; only a
  Core-committed action can produce the last.

## Verification performed

- Unit/integration: 434 tests (Core 14, reader-core 25, analysis 23, plus the existing
  suite). Browser acceptance (Playwright + Chrome, isolated instance, real atlas, mock
  provider): 164/164 page×operator combinations and 11/11 scenarios on both candidate
  policies, including server kill/restart; reports under
  `data/verification/browser_acceptance/20260925T2154*` and `…2156*`.
- Lead's own browser demonstration (`data/verification/core_v03_demo_2026-09-25/`):
  P1 → DEVELOP → P5 (offered sentence «As such, I do suppose that there is a fourth and
  other unspoken option.», development 2.75/3, confidence 0.75, assessment as-cc43…) →
  preview = vault text → Follow → P5 prose shown → refresh → server restart → same
  session, revision 2, 2 encounters, 3 journal events; journey page correct; state and
  decision replay OK with 0 provider calls; bundle exported with retained prose bytes.
- The reported P-page failure does not reproduce (investigator, browser, build f5847b0).

## Known limitations and remaining failures

1. **Manual navigation starts a new Core session.** Previous/Next, the page list, Back and
   "Continue here" begin a fresh journal at that page (Core has no relocate event yet),
   so a journey that mixes Follow with manual moves is split across sessions. Legacy
   `reader_state.json` still records everything. **Next concrete task:** add a
   `relocated` event (recorded action, bumps revision, creates an encounter with
   `via=manual`) so one session holds the whole ordered journey; then Back is a
   recorded action, not a new session.
2. **Bond wording is mechanical** (destination opening sentence). An authored offering
   sentence is an artistic decision — see the question below.
3. `resolve_options` still applies the Discovery/adjacency policy inside the options
   provider; the plan wants `policyAllows` as a separate logged gate with codes. The
   exclusion count is recorded on the offer set, not per candidate.
4. Refine (history refinement) still goes through the legacy option-set endpoint and
   persists a legacy option set + a session-log event; it does not touch Core state.
5. `/api/saved-result` and `/api/operator-options` are GETs that write; the future
   inspector must use only `/api/core/journey` and new `/api/analysis/*` routes.
6. The journal is authoritative but `data/core/sessions/` is a per-session JSONL, not
   SQLite; the plan permits either.
7. No score interpreter, simulator, matrix/evidence/operator-order inspector views, or
   copied-state route check exist yet. `test_reader_interaction.py`'s route-coverage
   list was edited by the reader worker (6 lines) to include the new GET routes.

## Artistic question for Brennan (not blocking)

Each offered bond currently quotes the destination's opening sentence as "the exact
literary sentence offering an action". Should bonds carry an authored offering sentence
instead (per source→destination→operator, versioned as a new bond version), and if so,
who authors them and in what voice? Until then the mechanical wording is labeled as such
on every bond (`wording_source: destination_opening_sentence`).

## How to run and inspect

```
.venv/bin/gibsey serve-reader            # reader; the session line shows id / revision / encounters
open http://127.0.0.1:8765/              # click an operator, Follow; then http://127.0.0.1:8765/journey
.venv/bin/gibsey core-sessions
.venv/bin/gibsey core-journey <session_id>
.venv/bin/gibsey core-replay <session_id> --export data/verification/bundles
.venv/bin/gibsey analysis-manifest; analysis-project; analysis-compose --ops ECHO,DEVELOP --source P1
.venv/bin/python tests/acceptance/run_browser_acceptance.py [--policy include-adjacent]
```
