# Core v0.3, session 1: contracts and file ownership

Governing document: `Gibsey_Core_v0.3_Weekend_Plan.md`. This note maps its contracts onto
the real checkout for the first session (persistent-Q slice + analysis contracts). It is
lead-owned; workers code against it. Nothing here calls a model.

## Baseline (observed 2026-09-25, before any change)

Branch `atlas-memory-exploration` @ `f5847b0`, tree clean except the untracked plan file.
Startup: `.venv/bin/gibsey serve-reader` (reader at 127.0.0.1:8765, PID 50122, serving
`f5847b0`). Tests: 372 passed, 1 skipped. Corpus: 41 pages; live atlas 1,640/1,640
complete under `cfg-5a7766c6c2012139e7bab61f` (rubric v2, jev-1.13.0). Real journey:
5 bonds, 6 Q_follow entries, 49 session-log events — preserved untouched.
The reported P-page failure (P1/P6 DEVELOP empty) **does not reproduce** on this build in
a real browser (investigator: 5 supported rows each, 0 provider dispatches); it was fixed
on 2026-09-21 and is not manufactured here.

## Component map (repository observation → v0.3 contract)

| v0.3 contract | Exists today | Status |
| --- | --- | --- |
| Content version | sha256 of file text (`corpus.Page.sha256`); no version field; `corpus_manifest.json` covers 20 pages only | **extend**: `core.identity.version_id` = `P1@<sha12>`; full sha256 kept alongside |
| Assessments + evidence | `data/atlas/assessments.jsonl` (exact texts sent, 7 distributions, model, hashes); Layer-2 Choice runs labeled field-relative | reusable; **no textual evidence spans exist** — inspector must say so |
| Bond version | `bonds.json` (5; 1 with hashes); no offered sentence | **extend**: `core.identity.bond_version_id` = hash(source version, destination version, operator, exact wording) |
| Offer set | `reader_option_sets.jsonl` keyed by page+policy, not by session revision | **replace for Core**: `offer_set_created` journal event at revision r |
| Session / state revision | none (one global `reader_state.json`) | **missing → core.journal + core.reducer** |
| Actions / dedup | `follow_token` returns earlier result even with a different payload | **missing → core.execute_action** (identical retry = recorded result; changed payload = `request_id_reused`) |
| Events / atomic commit | five files written in sequence under a thread lock | **missing → one atomic journal append per commit** |
| State reduction | imperative writes to `reader_state.json` | **missing → core.reducer.reduce (pure)** |
| Index manifest / projections / composition | none (numpy absent; `api._classify` gives latest-ok-per-pair) | **missing → analysis/** |
| Inspection | atlas panel, option Details, raw reader_state dump, `/demo/pr2`, `atlas-inspect` | reusable pieces; journey step-through **missing** |

## Identities

- `version_id = f"{page_id}@{sha256[:12]}"`; logical page id and version id are never
  interchangeable. Encounters, bonds, offers and manifest rows cite version ids.
- `bond_version_id = "bond_" + sha256({source_version, destination_version, operator, wording})[:20]`.
  Wording this session = the destination's exact opening sentence, `wording_source:
  "destination_opening_sentence"` (mechanical, not authored — an artistic decision is open).
- `offer_set_id` = hash of (session, revision, source version, operator, policy, ordered
  bond ids, options policy version): resolving twice at one revision returns the same set.
- `request_id` is client-supplied; its `fingerprint` = hash(session, offer_set_id,
  bond_version_id, expected_revision).

## Core (`src/gibsey_lab/core/`, lead-owned, written)

Journal `data/core/sessions/<session_id>/events.jsonl` (`core-event/1`): one line per
event, per-session `seq`, `revision_after`; single `write()` + fsync under file lock.
Event types: `session_started`, `offer_set_created`, `action_committed`,
`action_rejected`, `paused`, `resumed`, `presented`. State-changing (bump r):
session_started, action_committed, paused, resumed. Refresh/replay/retry write nothing.

Reducer: `State(v, page, z, H, c, ell, u, r, paused, requests, offer_sets, last_seq)`;
`H[i]` = `{encounter_index, version_id, page_id, via, event_seq, from_version,
bond_version_id, request_id, previous_encounter_index, return_index_distance,
intervening_encounters}`; encounter index is separate from event seq.

API (`core.core.Core`): `start_session(page_id, session_id=None)`,
`resume_session(session_id)`, `resolve_options(session_id, operator, policy=)`,
`execute_action(session_id, offer_set_id=, bond_version_id=, expected_revision=, request_id=)`,
`get_action_status(session_id, request_id)`, `pause`, `unpause`, `acknowledge_presented`.
Rejection codes: `request_id_reused`, `paused`, `stale_revision`,
`unknown_or_stale_offer_set`, `not_offered`, `source_mismatch`,
`destination_version_changed`, `source_version_changed`, `policy_ineligible`.
`Core(projectors=[...])`: each projector is called `(session_id, event, state)` AFTER the
commit; projections are derived and rebuildable, never authoritative.

## Ownership for this session

| Owner | Files |
| --- | --- |
| Lead | `notes/core-v03-*.md`, `src/gibsey_lab/core/**`, `tests/test_core_*.py`, `cli.py`, `README.md`, git |
| R (reader integration) | `src/gibsey_lab/reader/**`, `src/gibsey_lab/core/projectors.py` (mirror to legacy files), `tests/test_reader_core*.py`, `tests/acceptance/**` |
| A (analysis) | `src/gibsey_lab/analysis/**`, `tests/test_analysis_*.py` |

## Reader integration contract (R)

Endpoints (all JSON, no provider calls):
- `POST /api/core/session {page?, session_id?}` → start or resume (the client keeps
  `session_id` in localStorage; absent/unknown → start at the reader's last page).
- `GET /api/core/session?session_id=` → `resume_session`.
- `POST /api/core/options {session_id, operator, policy}` → `resolve_options` (pure
  read + one non-bumping journal event; **no session-log event, no option-set file**).
- `POST /api/core/execute {session_id, offer_set_id, bond_version_id, expected_revision, request_id}`
  → `execute_action`; CoreError → HTTP `status` with `{code, reason, details}`; a duplicate
  returns 200 `{duplicate: true, ...}`.
- `GET /api/core/status?session_id=&request_id=`.
- `GET /api/core/journey?session_id=` → read-only inspection: every encounter with exact
  prose (from the manifest by version id; if the version is no longer current, say so and
  show nothing fabricated), the offer set that produced it (ordered bonds, wording,
  tiers, operator fit, assessment ids), the selection, and state before/after (r, counts,
  return spacing). This GET must not write anything.
Projectors (`core/projectors.py`): after `action_committed`, mirror to legacy stores so
existing panels keep working: `bonds.json` entry keyed by bond_version_id with both
hashes; `reader_state.json` active page + history entry with `follow_token=request_id`;
session-log `operator_proposed/offer_accepted/accept_and_follow/q_traversal/page_viewed`
with `core_event_seq`, `session_id`, `version_id`. Idempotent per event seq.
Frontend: operator buttons → `/api/core/options`; Follow → `/api/core/execute` with
`expected_revision` from the current session state and a fresh `request_id` per click
(reused on retry of the same click); `session_id` persisted in localStorage; on load →
resume; a stale-revision 409 shows the current revision and re-resolves; `Continue here`
semantics unchanged. Keep `data-testid` hooks; add `data-session-id`, `data-revision`.
The old `/api/operator-options` + `/api/follow-option` stay for one release but the
buttons no longer use them.

## Analysis contracts (A) — `src/gibsey_lab/analysis/`

`index_manifest.py`: `build_manifest(field, atlas_config) -> dict` with
`{schema:"index-manifest/1", manifest_id, page_order:[{index, page_id, version_id, sha256}],
operator_order:["ECHO","DEVELOP","CONTRADICT","BRIDGE"], dimension_of:{...},
snapshot:{atlas_config_id, rubric_version, pinned_returned_model, assessment_set_sha256,
records_in_store, corpus_sha256}, projection_rule:"binary-projection-v1", support_floor: 2/3,
collapse_rule:"latest compatible ok record per pair", N:41, O:4}`; `manifest_id` = hash of
page_order + operator_order + snapshot; page order = authored order (explicit list, never
`Field.all_ids()`); `offset(i,j,o)=((i*N)+j)*O+o` and `decode(offset)`; write to
`data/atlas/index_manifest.json`.
`projection.py`: `project(manifest) -> {M: {op: 41x41 ints}, S: {op: 41x41 status codes
in {included, assessed_below_floor, unassessed, stale, failed, self}}, A: {op: 41x41
floats or None}, assessment_ids: {op: 41x41}, counts}`; `M_o[i][j]=1` iff status
`included`; policy is NOT applied (Discovery is a separate mask,
`eligibility_mask(field, policy)`); duplicates collapse to one edge with
`duplicates_collapsed` counted.
`composition.py`: pure-Python `compose(M_first, M_second, source_index=None) ->
{counts: 41x41 ints, witnesses(i,j): [(i,k,j)...] sorted by manifest index, cap 100,
truncated flag, exact total kept}`; `route_id` per witness = hash(manifest_id,
projection_rule, op sequence, [(v0),(op1,assessment_id1,v1),(op2,assessment_id2,v2)]);
label `kind: "relation_walk"`.
Fixture (`tests/test_analysis_composition.py`): the plan §4.8 graph A→B ECHO, A→C DEVELOP,
B→C DEVELOP, C→B ECHO — ECHO→DEVELOP from A = {C via B}; DEVELOP→ECHO from A = {B via C};
matrix counts equal independently enumerated witnesses (a second, naive enumerator in the
test). Labeled "mathematical fixture check", separate from any corpus result. A real-corpus
E@D vs D@E summary is written by `gibsey analysis-compose --ops ECHO,DEVELOP` to
`data/analysis/` with the manifest id, and labeled "relation walks, not score-valid".
CLI: `analysis-manifest`, `analysis-project`, `analysis-compose`.
