# Atlas + reader-memory milestone: team contracts

Lead-owned. Workers code against this file; propose changes to the lead, do not edit it.
Governing documents: `Gibsey_Lab_Relationship_Atlas_and_Reader_Memory_Milestone.md`
(milestone) and `QDPI-master-function-matrix.md` (QDPI semantics). The separately named
"relationship and memory reset" document was **not present** in the repository or on this
machine when work began (searched by name and content); nothing here is derived from it.

Scope guard: Q→Q only. No A/L generation, no Vault expansion, no mandatory forms. BRIDGE
and `bridge_relation` are experimental relationship labels, not QDPI L. Assessments are
evidence for possible bonds — never bonds, human judgments, or reader preferences.

## 0. Working rules

- One shared checkout (`main` @ 1935bb7 + uncommitted user data). No worktrees: isolation
  is by strict file ownership below. Do not `git commit`, `git stash`, `git checkout`, or
  reset anything.
- Workers never make live provider calls, never read `.env`, never touch `data/`, `runs/`,
  `vault/`, or port 8765 (the user's real reader is running there). Tests use `tmp_path`
  and mocks only. Only the lead dispatches live jobs or writes `data/atlas/ledger.jsonl`.
- Python ≥3.10, standard library + existing deps only. Match existing style (module
  docstrings that state guarantees, `from __future__ import annotations`, dataclasses,
  module-level path constants that tests can monkeypatch).
- Every store is append-only JSONL. Never rewrite or delete a historical record;
  "current" is always a computed view.

## 1. File ownership

| Owner | Files (create/edit) |
| --- | --- |
| Lead | `notes/atlas-memory-contracts.md`, `src/gibsey_lab/scoring.py` (exists — shared types + provider gateway interface), `src/gibsey_lab/jev_client.py`, `src/gibsey_lab/mock_client.py`, `src/gibsey_lab/results.py`, `src/gibsey_lab/cli.py`, `README.md`, `notes/atlas-memory-status.md`, `pyproject.toml` |
| B atlas | `src/gibsey_lab/atlas/**` , `tests/test_atlas_*.py` |
| C memory | `src/gibsey_lab/memory/**`, `tests/test_memory_*.py` |
| D reader | `src/gibsey_lab/reader/**`, `src/gibsey_lab/state.py`, `src/gibsey_lab/session_log.py`, `tests/test_reader_*.py`, `tests/test_state.py` |

Everything else is read-only for workers. CLI: each package exposes
`register_cli(subparsers) -> None` in `<package>/cli.py`; the lead wires it into `cli.py`.

## 2. Shared provider layer (lead, `scoring.py`) — already written, import it

```python
@dataclass(frozen=True)
class ScoreQuestion:  qid: str; instructions: str; levels: tuple[str, ...]   # low→high, 2–10
@dataclass(frozen=True)
class ScoreRequest:   kind: str            # "base_pair" | "contextual"
                      state: dict          # exact model-visible JSON state
                      questions: tuple[ScoreQuestion, ...]
                      requested_model: str
                      def request_sha256(self) -> str   # canonical hash of state+questions+model
@dataclass(frozen=True)
class ScoreAnswer:    qid; score: float; max_level: int; confidence: float|None;
                      probabilities: dict[str,float]; legend: dict[str,str]; valid: bool; problems: list[str]
@dataclass(frozen=True)
class ScoreOutcome:   status: str          # "ok" | "invalid" | "error" | "budget_refused"
                      mode: str            # "live" | "mock"
                      requested_model; returned_model; answers: dict[str,ScoreAnswer];
                      usage: dict|None; elapsed_seconds; attempts: int; errors: list[str];
                      request_sha256: str; ledger_ids: list[str]
Dispatch = Callable[[ScoreRequest], ScoreOutcome]
def mock_dispatch(request) -> ScoreOutcome       # deterministic, mode="mock", returned_model="mock-lexical-overlap-v1"
def make_live_dispatch(cfg, ledger) -> Dispatch  # lead-only wiring; SDK retries disabled, ≤2 own retries, every attempt ledgered
```

B and C take a `dispatch: Dispatch` argument everywhere a provider call is needed and test
with `mock_dispatch` or their own fakes. A failed live call is `status="error"`; it is
never converted to a mock result. `mode` is set by the dispatch, never by the caller.

Model-visible identification: endpoints are identified by **role keys inside `state`**
(`source_page`, `destination_page`, `reading_history`, `current_page`,
`candidate_destination`) and every question's `instructions` names those keys and the
direction explicitly. Corpus page IDs are **not** shown to the model (IDs such as PR1/PR2
leak authored position); they live in provenance only.

## 3. Layer 1 — base pair profiles (B)

Dimensions (fixed order, these exact ids): `direct_q_fit`, `echo`, `development`,
`contradiction`, `bridge_relation`, `redundancy`, `missing_context`. One Score question
each, 4 descriptive levels (0 absent … 3 strong), all seven batched in one request per
directed pair; state = `{"source_page": {"text"}, "destination_page": {"text"}}`.
`atlas/rubrics.py` holds `RUBRIC_VERSION` + exact wording; a wording change is a new
version, old versions stay importable. Original operator criteria
(`relational_operators.py`) are untouched.

Assessment record (one JSONL line in `data/atlas/assessments.jsonl`, path constant
`atlas.store.ASSESSMENTS_PATH`):

```
{schema: "atlas-assessment/1", assessment_id, at, job_id, mode, source_id, destination_id,
 source_sha256, destination_sha256, rubric_version, config_id,
 requested_model, returned_model, request_sha256, state, questions,
 status: "ok"|"invalid"|"error", dimensions: {dim: {score, score_norm, max_level,
 confidence, probabilities, valid, problems}}, usage, elapsed_seconds, attempts, errors}
```

`config_id` = hash of (schema, rubric_version, dimension set, state layout, pinned
returned-model id). Pair status under the active config, computed (never stored):
`complete` (a record with status ok, all 7 dims valid, both hashes == current manifest,
config match, mode match) · `stale` (only ok-records whose hash/config/model no longer
match) · `failed` (only error/invalid records) · `unassessed`. A low score is a valid
value: `complete`. Mock and live coverage are always separate views; records with a
different `returned_model` are never pooled.

Public API (`atlas/api.py`), used by C, D, lead:

```python
active_config(mode) -> dict
pair_status(source_id, destination_id, mode="live") -> dict      # status + latest compatible record
profiles_for_source(source_id, mode="live") -> list[dict]        # exactly 40 rows, every status represented
coverage(mode="live") -> dict                                    # complete/failed/stale/unassessed counts of 1640, per-source
build_missing(dispatch, mode, *, limit=None, pairs=None, concurrency=2, job_id=None) -> dict   # resumable; skips compatible complete pairs
```

CLI (B): `gibsey atlas-inspect SRC DST`, `atlas-coverage`, `atlas-build [--mock|--live]
[--limit N] [--pairs A:B,...]`, `atlas-resume`. Layer 2 (historical Choice distributions)
is exposed read-only as `atlas/choice_history.py: choice_rows_for_pair(src, dst)` labeled
field-relative; it never feeds `dimensions`.

Ledger (`atlas/ledger.py`, B implements, only the lead runs it live):
`data/atlas/ledger.jsonl`, one line per event `reserve|settle|release`. Hard caps are
constants: 2000 attempts, 10_000_000 input tokens, concurrency 2, ≤2 retries/request.
`reserve(request, est_input_tokens)` refuses (→ `budget_refused`) if settled + in-flight
would exceed a cap; totals are **recomputed from the file on every start**, so restart
never resets the allowance; an unsettled reservation from a dead process counts as spent
at its estimate; missing usage is settled at the estimate and flagged `usage_unknown`.
Thread-safe (single process, lock). Mock dispatch never touches the ledger.

## 4. Layer 3 — memory + contextual assessment (C)

Memory packet (`memory/packet.py`, `MEMORY_POLICY_VERSION = "memory-v1"`), built from
session-log events + manifest, never from client state:

```
{schema: "memory-packet/1", policy_version, field, candidate_policy, current: {page_id, sha256},
 window: 6, encounters: [{seq, page_id, sha256, text, arrived_via, operator|null, at, revisit: bool,
                          version_source: "event"|"current_manifest"}],   # oldest→newest, excludes current
 omitted_earlier_encounters: int, intention: str|null, trace_ref: {log_path, first_seq, last_seq}}
```

Encounter = `page_viewed` or `back` event (a Back is a new encounter of the page returned
to, `arrived_via="back"`, `revisit=true`; nothing is removed). Consecutive duplicate views
of the same page collapse. `model_visible_state(packet)` returns exactly what is sent:
ordered texts + neutral arrival labels ("followed a DEVELOP offer", "next page", "back",
"picked from list"). No inference about liking/agreement; no human notes, reviewer text,
or page IDs in provider input.

Pipeline (`memory/offers.py`, `OFFER_POLICY_VERSION`, `SHORTLIST_POLICY_VERSION`):

```python
build_offers(field, page_id, events, *, policy, dispatch, mode, intention=None,
             memory_override=None, reuse_cache=True) -> OfferResult(dict)
```

Steps, each recorded in the result: 40 base profiles (`atlas.api`) → eligibility
(candidate policy; incomplete/stale/failed profiles are ineligible and counted) →
deterministic shortlist (≤8; per-dimension support, no single universal score; every
entry carries `reasons`) → memory packet → contextual assessment of **the shortlist only**
(3 Score questions per candidate: `works_after_history`, `grounded_reading_effect`,
`repeats_recent_reading`; one request per candidate) → qualification + ranking → ≤3
offers. No randomness. Never pads to three; never forces an operator, a cross-text jump,
or bans revisits/neighbors.

OfferResult: `{schema: "offer-result/1", offer_set_id, at, field, page_id, page_sha256,
policy, mode, state: "offers"|"no_qualified"|"no_candidates"|"atlas_incomplete"|"error",
memory_packet, memory_sha256, base_counts, shortlist: [...], assessed_ids: [...],
not_assessed_count, offers: [{destination_id, destination_sha256, relation_labels: [...],
base: {...7 dims}, contextual: {...3 qs}, contextual_assessment_id, from_cache: bool,
rank, rank_reasons}], rejected: [{destination_id, reasons}], versions: {...}, usage, errors}`.

Contextual cache key = sha256 of (current+candidate hashes, `memory_sha256` of the exact
model-visible memory, memory/contextual rubric versions, requested+returned model, atlas
`config_id`). Store: `data/contextual/assessments.jsonl`, `data/contextual/offer_sets.jsonl`.
A base profile reused in an offer is labeled base; only a record under this key is
"history-conditioned".

PR2 demo (`memory/demo.py`): fixtures A `PR1→PR3→PR2`, B `LF3→PR2`, C no history, via
`memory_override`; shortlist computed once and held fixed; writes
`data/demos/pr2_memory/*.json` + a static `comparison.html`. CLI: `gibsey offers PAGE`,
`gibsey memory-packet`, `gibsey pr2-demo [--mock|--live]`.

## 5. Reader (D)

Outcome states (exact ids): `not_requested`, `loading`, `selected`, `abstained`,
`no_candidates`, `error` (+ `no_qualified` for offer hands). Every operator request and
offer request appends to `data/reader_outcomes.jsonl` (`reader/outcomes.py`) with
`outcome_id`, `request_id`, state, page+hash, policy, run_dir/offer_set_id; reruns append,
earlier outcomes stay listed in the UI ("earlier results" per page+operator).
Server-side single-flight per (page, operator|offers, policy) key + client `request_id`
echo: duplicate clicks join the in-flight call; a response whose `request_id` is not the
latest for the current page is recorded but not applied. GET requests never dispatch.

Follow (`POST /api/follow-offer`, and the existing accept-and-follow): server validates at
follow time — destination in field, eligible under the recorded policy, source+destination
sha256 == current manifest, client `from_page` == server `active_page` — then
propose → accept → follow as three separate records (bond carries both endpoint hashes),
idempotent per `follow_token`. Session events gain `seq`, `page_sha256`, `request_id`.
Event order for a follow: `offer_proposed` → `offer_accepted` → `q_traversal` →
`page_viewed(via=traversal)`.

Endpoints D adds: `POST /api/offers` (calls `memory.offers.build_offers`),
`GET /api/offers/latest`, `GET /api/outcomes`, `GET /api/atlas/profiles?source=`
(calls `atlas.api.profiles_for_source`), `GET /demo/pr2` (serves the static comparison).
`server.OFFER_DISPATCH_FACTORY` is a module-level hook the lead wires to the live gateway;
D's tests set it to mock. Cards show destination id, relation labels, exact-text preview;
details expandable. No generated rationale text. Agent commentary, if shown, is labeled
with agent name + "interpretation". Manual navigation, Preserve, and the optional note
stay as they are.

## 6. Integration order

1. Lead: `scoring.py` (done before workers start). 2. B, C, D in parallel on mocks.
3. Lead wires CLI + live dispatch, runs full tests. 4. B and C each trace the integrated
pipeline once. 5. Lead: pilot → reviewers → freeze → live build → PR2 demo.
6. Fresh reviewer E. 7. Status doc + reader restart.

## 7. Audit findings that bind the implementation (auditor, 2026-09-20, read-only)

- 465 run dirs: 464 live (all returned `jev-1.13.0`), 1 mock, every one a single Choice
  question. **No independent pair assessment exists**; Layer 1 starts at 0/1,640. Layer 2:
  408 live destination-Choice runs touch 922 directed cells (800 within-corpus under v0.1
  unrestricted; 122 cross-corpus from full-41 reader runs). B exposes them read-only with
  field, policy, criteria version, candidate count, and requested/returned model per row.
  `relop-reverse` (53 pairs) is relative operator typing — also Layer 2, never Layer 1.
- The reported PR1→PR3→PR2 route is not in any record. Recorded: PR1→DEVELOP→PR4→BRIDGE→PR2,
  fresh live call, policy discovery, PR3/PR5 excluded, 39 candidates. Discovery was not
  violated. Real defects found on that path, all D's: no follow-time validation
  (`state.propose` accepts any run_dir); `state.follow` writes `from_page` from the stale
  stored `active_page` instead of the bond's source; a double operator click spent a live
  call whose response was then dropped; no server-side in-flight dedupe; transport errors
  are never persisted; same-second reruns collide in `recorder.record_run` (D may guard
  this in the server; `recorder.py` stays unedited).
- Legacy session events (26) have no `seq`, no page hash, `from_page` always null, and do
  not log policy. C must accept them: `seq` falls back to line index, `version_source` is
  `"current_manifest"` when the event carries no hash. D adds `seq`, `page_sha256`,
  `policy`, `request_id` to new events without rewriting old lines.
- 3 existing tests fail only because they assert against the real `runs/` dir
  (`test_reader_server.py` ×2 — D fixes by pointing them at `tmp_path`;
  `test_saved_runs.py::test_full_41_field_has_no_recorded_v0_2_results_yet` — lead).

## 8. Exploration repair (2026-09-21) — operator options contract

Reproduced cause (records, not assumption): the four operator buttons still call the
single-winner Choice path (`/api/request-selection`, 38 candidates + NONE). P1 DEVELOP →
recorded NONE 0.15; P6 DEVELOP → new NONE 0.14; PR4 CONTRADICT → NONE 0.41 — while the
atlas holds P1→P5 development 0.92 and P6→PR3 0.90. The route hand builds one global
shortlist before any operator is considered and then thresholds it (PR1: "1 route
qualified of 4 assessed"). No HTTP 4xx/5xx, no exception, atlas complete, server and
served `app.js` are the current build.

**Product rule.** For every page × {ECHO, DEVELOP, CONTRADICT, BRIDGE}: at least three
distinct eligible destinations whenever ≥3 eligible pages exist, from the existing live
atlas, with no provider call. Accessibility (can be previewed/followed) is separate from
support (how strongly the assessed relationship fits the operator). Scores are never
altered; weak fits are labeled, not hidden and not relabeled.

Ownership: **S (selection)** `src/gibsey_lab/memory/operator_options.py` (new),
`memory/cli.py`, `tests/test_memory_operator_options.py`. **I (interaction)**
`src/gibsey_lab/reader/**`, `state.py`, `session_log.py`, `tests/test_reader_*.py`,
`tests/test_state.py`. **Lead** contracts, `cli.py`, `pyproject.toml`,
`tests/acceptance/**` (browser harness), status doc, live calls, git.

```python
OPERATOR_DIMENSIONS = {"ECHO": "echo", "DEVELOP": "development",
                       "CONTRADICT": "contradiction", "BRIDGE": "bridge_relation"}
OPTIONS_POLICY_VERSION = "operator-options-v1"
operator_options(field, page_id, operator, *, policy, mode="live", profiles_provider=None,
                 atlas_config_provider=None, max_supported=5, min_shown=3) -> dict
refine_with_history(option_set, field, events, *, dispatch, mode, requested_model,
                    intention=None, reuse_cache=True) -> dict
```

`operator_options` result (`operator-options/1`), pure and deterministic, never dispatches:
`{schema, policy_version, option_set_id (content hash), field, page_id, page_sha256,
operator, dimension, policy, mode, atlas_config_id, ordering_basis: "base_assessments",
support_floor, counts: {eligible, usable, unusable, supported, exploratory_shown,
ineligible_policy}, unusable: [{destination_id, status}], state:
"options"|"fewer_than_three_eligible"|"no_candidates"|"atlas_unavailable", options: [...]}`.
Each option: `{destination_id, destination_sha256, tier: "supported"|"exploratory",
tier_label ("Supported" | "Exploratory — weak or uncertain fit"), operator_fit: {dimension,
score, score_norm, confidence, nearest_level}, cautions: [...], base: {7 dims: score,
score_norm, confidence}, assessment_id, is_authored_neighbor, rank, rank_reasons}`.

Ranking v1: consider **every** eligible destination with a `complete` profile under the
active config whose endpoint hashes equal the current manifest (others are listed in
`unusable`, never scored as zero). Supported = operator dimension `score_norm ≥ 2/3`
(rubric level 2, same floor as shortlist-v2). Order supported by operator fit desc, then
`direct_q_fit` desc, then field page order; show up to `max_supported`. If fewer than
`min_shown` are supported, append the best remaining by the same ordering as
**exploratory** until `min_shown` are shown. `cautions` are descriptive flags, never
exclusions and never score changes: `low_confidence` (<0.5), `high_redundancy` (≥2/3),
`high_missing_context` (≥2/3), `low_direct_q_fit` (<1/3). No randomness, no hardcoded ids.

`refine_with_history` assesses exactly the displayed options with the existing
contextual questions/cache (`memory.contextual.assess`) against the memory packet built
from `events`. It **never removes an option**. Result = the same option set plus per-option
`contextual` answers (or `contextual_error`), `ordering_basis: "reading_history"` only if
every displayed option has a valid answer, else `"base_assessments"` with
`refinement: {state: "partial"|"failed"|"ok", errors, memory_sha256, assessed_ids}`.
History ordering: tier first, then `works_after_history` score desc with candidates
within 0.15 treated as tied (ties keep base order — the measured rerun noise is ≤0.10),
then base order. Tier and labels never change under refinement.

Reader (I): each operator button → `GET /api/operator-options?page=&operator=&policy=`
(no dispatch; persists the option set idempotently to `data/reader_option_sets.jsonl`) →
ranked list with tier badge, operator fit + confidence, cautions, exact-text preview,
Follow. `POST /api/refine-options {option_set_id, request_id}` → single-flight, options stay
visible while it runs, applied only if page/history/policy still match, failure/abstention
keeps base options with an explicit "ordering: base assessments — history refinement
failed/unavailable" line. `POST /api/follow-option {option_set_id, destination_id,
from_page, follow_token}` → same validation as follow-offer (field, policy eligibility, both
hashes, reader position, idempotent token) → propose / accept / follow as separate records;
bond + events carry `operator`, `tier`, `operator_fit`, `option_set_id`,
`proposal_kind: "operator_option"`; an exploratory follow is recorded as the reader's
explicit choice and never writes a review/judgment. The single-winner Choice request
stays available as an explicit secondary research action ("Ask Jev for a single pick");
its abstentions/errors remain recorded and listed and never hide the ranked options.
The old cross-operator hand is no longer the default exploration surface.
