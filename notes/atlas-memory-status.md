# Relationship atlas + reader memory: implementation status

As of 2026-09-20 (end of the milestone session). Written for a fresh Claude Code session
or a human who has none of the conversation. Companion files:
`notes/atlas-memory-contracts.md` (interfaces, ownership, audit findings),
`notes/atlas-pilot-calibration.md` (pilot, blind reviewer readings, rubric v1→v2).

**Governing documents.** `Gibsey_Lab_Relationship_Atlas_and_Reader_Memory_Milestone.md`
and `QDPI-master-function-matrix.md`. The milestone refers to a separate "Gibsey Lab:
Relationship and Memory Reset" document; it was **not in the repository or findable on the
machine** (searched by filename and content, twice), so nothing here derives from it. If
it exists, compare it against this file before extending the work.

**Scope held.** Q→Q only. No A/L generation, no Vault expansion, no required forms.
`bridge_relation` is an experimental relationship label, not QDPI L. Assessments are
evidence for possible bonds — never bonds, human judgments, or reader preferences.

## 1. What exists now

| Layer | What | Where | Status |
| --- | --- | --- | --- |
| 1 Base pair profiles | 7 independent Score dimensions per directed pair, all 41×40 pairs incl. authored neighbors | `data/atlas/assessments.jsonl` (append-only) | **1,640 / 1,640 complete, live** |
| 2 Field-relative Choice | 408 historical live Choice runs touching 922 directed cells | `runs/` (read-only), shown by `atlas-inspect` | recovered, labeled, never used as pair scores or in selection |
| 3 History-conditioned | 3 contextual Score questions per shortlisted candidate, keyed by the exact memory sent | `data/contextual/assessments.jsonl` | 30 live records = PR2 fixtures × 2 runs; 2 more from the lead's live check in `data/verification/` |

Pipeline (each step recorded in the offer result): current page → 40 base profiles →
eligibility (policy; only `complete` rows under the active config) → deterministic
shortlist ≤8 with reasons → memory packet from the server-side session log → contextual
assessment of the shortlist only → qualification + ranking → ≤3 offers → proposal →
acceptance → Q traversal → history.

Code: `src/gibsey_lab/scoring.py` (request/outcome types, mock + live dispatch),
`live_gateway.py` (the only place a ledgered live dispatch is built), `atlas/`, `memory/`,
`reader/` (+ `reader/outcomes.py`), `state.py`, `session_log.py`, `jev_client.py`.

## 2. Active versions

- Atlas: schema `atlas-assessment/1`, rubric **`atlas-rubric-v2`** (v1 importable,
  unchanged; v2 differs only in `bridge_relation`), config
  **`cfg-5a7766c6c2012139e7bab61f`** frozen 2026-09-20T19:10:53Z
  (`data/atlas/active_config.json`). Requested and pinned returned model
  **`jev-1.13.0`** (the `jev-latest` alias resolved to it in the pilot; a different
  returned model is recorded `invalid`, never pooled). Dimensions: `direct_q_fit`, `echo`,
  `development`, `contradiction`, `bridge_relation`, `redundancy`, `missing_context`;
  4 levels each; one request per pair; state = the two page texts under role keys
  `source_page` / `destination_page`; **page IDs are never shown to the model**.
- Memory: `memory-packet/1`, policy **`memory-v2`**, window 6 encounters, omitted count
  stated, exact page text, neutral arrival labels, no IDs/hashes/notes/inference. Back adds
  an encounter; nothing is erased. (v1→v2: operator follows now read "followed a BRIDGE
  operator selection"; hand follows read "followed an offered route".)
- Contextual rubric `contextual-rubric-v1`: `works_after_history`,
  `grounded_reading_effect`, `repeats_recent_reading`.
- Shortlist **`shortlist-v2`**, offers **`offers-v2`** — *provisional application policy*:
  relation floor 2/3 (expected score ≥ rubric level 2, the first level asserting something
  definite; also governs card labels), `direct_q_fit` ≥ 0.34, `missing_context` ≤ 0.67,
  `redundancy` > 0.67 admits via echo only; top 2 per relation, cap 8; qualification
  works ≥ 2/3, effect ≥ 2/3, repeats ≤ 0.67; rank by rounded works, effect, repeats, then
  best base relation, then page order. No randomness. v1 floors were 0.5; changed before
  any live contextual data existed because 48–75% of pairs cleared 0.5.
- Reader outcome states: `not_requested`, `loading`, `selected`, `abstained`,
  `no_candidates`, `error`; hands: `offers`, `no_qualified`, `no_candidates`,
  `atlas_incomplete`, `error`. All persisted in `data/reader_outcomes.jsonl`.

## 3. Coverage

`gibsey atlas-coverage --mode live` → complete 1,640 · failed 0 · stale 0 ·
unassessed 0 · 41/41 sources · single returned model. Independently recomputed from the
raw records and current vault hashes by the reviewer (not via `atlas.api`): same result;
every reverse pair has its own state and request hash; 8 v1 pilot rows not pooled; no mock
rows. Mock coverage: 0 (mock is only ever written under temp dirs by tests).
Shortlist sizes from the live atlas under Discovery: 2–7 per page, typically 5
(support: echo 77, development 80, bridge 80, contradiction 12 — only 1% of pairs reach
the contradiction floor).

## 4. Live provider work (Jev only — not Claude usage)

| Ledger | Attempts | Failed | Input tokens (all reported, none estimated) |
| --- | --- | --- | --- |
| milestone `data/atlas/ledger.jsonl` | 1,678 of 2,000 | 0 | 5,119,421 of 10,000,000 |
| reader `data/reader_ledger.jsonl` | 2 of 600 | 0 | 4,437 |
| **total** | **1,680** | **0** | **5,123,858 ≈ $0.215** at $0.042/M input (output free) |

Breakdown: pilot v1 8 · re-pilot v2 8 · atlas build 1,632 · PR2 demo 15 + 15 (replicate
under memory-v2) · lead live HTTP check 2. Zero retries were needed. Jobs:
`atlas-live-20260920T190417Z-110072` (pilot v1), `…T191039Z-7ca7fa` (pilot v2),
`…T191103Z-bfd29e` (build; log `data/atlas/build_live_20260920.log`). ~2,930–3,400
tokens/request. Not in any ledger: the four operator Choice runs the user made at
16:53–16:57Z, before the Choice path was ledgered.

**Resume / rebuild.** `gibsey atlas-build --live` (or `gibsey atlas-resume`) assesses
exactly the pairs that are not `complete` and skips the rest; safe to interrupt. After a
vault page is edited its 80 pairs read `stale` and that command re-assesses them, leaving
old records in place. Remaining milestone allowance: 322 attempts. The ledger totals are
recomputed from the file under a lock, so restarting never resets them.

## 5. Reported reader problems — findings

- **PR1→DEVELOP→PR3→BRIDGE→PR2 is not in any record.** The log shows
  PR1→DEVELOP→**PR4**→BRIDGE→PR2 (16:53–16:55Z): fresh live call, policy discovery, PR3 and
  PR5 excluded, 39 candidates, PR2 chosen at 0.36. PR3 was the DEVELOP runner-up (0.22)
  and the label on PR4's Previous button. Discovery was not violated. What *was* missing:
  any follow-time validation — now added (destination in field, eligible under the
  recorded policy, both endpoint hashes current, reader actually on the source page per
  the log, memory still current for hands; 409 and nothing moves otherwise).
- **"abstained (NONE) — no eligible destination"**: two states in one sentence; split.
- **Vanishing NONE on "Ask Jev again"**: single result slot overwritten by every request;
  `/api/saved-result` returned only the newest run; a CSS rule defeated `[hidden]`. Now
  every outcome (incl. abstentions, errors, rejected follows) is appended and earlier ones
  stay listed; the three PR2 CONTRADICT abstentions are backfilled from `runs/`.
- Also fixed: double click spent a live call and dropped it (server-side single-flight +
  request ids); same-second rerun crash; `state.follow` wrote a stale `from_page`;
  legacy `/api/follow` and `/api/review` were unguarded; stale-history hands were shown as
  current; offer follows were logged as operator requests; operator Choice calls used the
  SDK's hidden retries with no ledger.

## 6. PR2 memory demonstration (fixtures — not the reader's actions, not bonds)

`data/demos/pr2_memory/` (run 2, memory-v2) and `data/demos/pr2_memory_run1_memory-v1/`;
readable page at `/demo/pr2` or `comparison.html`. Conditions A PR1→PR3→PR2, B LF3→PR2,
C no history; shortlist `[PR4, P6, LF7, LF8, LF14]`, order, questions, model, policies held
constant; static base-only ranking identical in all three; 15 distinct request hashes.

*Software:* history reaches the provider (exact page texts verified in the stored state),
cache keys are memory-strict, the comparison is reproducible. Two identical runs differ by
**≤ 0.10** on every one of 45 answers, and all 15 qualification decisions repeat.
*Reading (lead-agent interpretation, not a human judgment):* the robust effect is that the
London Fox candidates depend on arrival — LF7 `works_after_history` 1.63–1.70 after
PR1→PR3, 2.16 with no history, 2.51 after LF3; LF8 1.1 / 1.75 / 2.03 — so they qualify
after LF3 (London and her chatbot → the chatbot's text and functions) and not after the
Princhetta path. That is 5–9× the noise and textually sensible.
*Weak:* PR4 and P6 lead every hand; `grounded_reading_effect` is compressed (2.1–2.75,
confidence 0.4–0.75); **the order of qualified candidates and the identity of the third
card are not stable across identical runs**, because ranking rounds to levels and values
cluster near 2.5 (B: P6, LF14, PR4 → PR4, P6, LF7). Defensible: *which pages qualify*.
Not defensible: *which is first*. Left as is — no tuning loop. Fixture arrivals are
"arrival not specified"; they do not exercise arrival labels.

## 7. Verification performed

- 313 tests pass, 1 skipped (was 100 pass / 3 fail at session start; those 3 asserted
  against the real `runs/`). New: atlas 62, memory 57, reader 127, live-dispatch 12
  (fake SDK: hidden retries off, one reservation per attempt, ≤2 retries, permanent errors
  not retried, refused budget makes no call, model pin).
- Offline end to end (mock atlas → offers → follow) in temp dirs, by C, D and the reviewer.
- Live end to end over HTTP by the lead on a scratch instance (port 8791, temp session):
  two simultaneous identical offer clicks → one dispatch set; wrong-page and not-offered
  follows refused; valid follow = proposal, acceptance, traversal as separate records,
  bond pinning both hashes; duplicate token = one traversal. Records:
  `data/verification/livecheck_20260920/`.
- Browser (Chrome) by D on a smoke server with a fake provider: refresh dispatches
  nothing, earlier NONE stays visible during a rerun, one operator's result does not clear
  another's, mid-flight navigation never moves the reader, Back stack survives reload.
- Two pipeline traces (B atlas-side, C memory-side) and one fresh independent reviewer;
  every confirmed defect was fixed in code and re-tested (list in §5).
- **Not verified:** light-mode visuals; long sessions with >6 encounters against the live
  provider; behaviour when the alias moves to a new model (by design the pin makes those
  results `invalid` until a new config is frozen).

## 8. Known limitations

1. Offer ordering is noise-sensitive (see §6). Next step if wanted: treat candidates within
   ~0.15 as tied and order ties by a stated rule, as `offers-v3`.
2. Jev reads generously on weak pairs (pilot: intended-weak P7→LF13 got direct fit 1.9 and
   development 1.85 where blind reviewers read 0–1). 63% of floor-clearing base relation
   scores have confidence < 0.5; confidence is shown but not used in selection.
3. Rubric v2 weaknesses reported by the reviewers and left alone: echo/bridge can credit
   the same structural feature; development level 3 shades into contradiction level 2;
   `direct_q_fit` has a practical floor of 1 within a book; boilerplate maxes echo;
   `missing_context` cannot tell withholding from dependence.
4. Contradiction almost never reaches the floor (1% of pairs), so hands are mostly echo /
   development / bridge. Nothing forces a contradiction, by requirement.
5. Reviewer levels are agent interpretations. **No human literary judgment exists for any
   atlas or contextual value.** Software correctness is established; whether the reading
   experience is more meaningful is not, beyond the one LF7/LF8 effect above.
6. `data/corpus_manifest.json` still lists only the 20 P/F pages (hashes correct). The
   generator scripts for the historical `relop-*` batches are not in the repo.
7. Each real hand is stored twice (`data/contextual/offer_sets.jsonl` and
   `data/reader_offer_sets.jsonl`); redundant, harmless.

## 9. Team record

Native Claude Code Agent Teams (v2.1.278, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`),
lead + named teammates, never more than three active. One shared checkout with strict file
ownership instead of worktrees (worktrees would have omitted the uncommitted milestone
doc, contracts and shared scoring layer). Only the lead made live calls.
Integrated: **auditor** (read-only audit; route finding) · **atlas-engineer** (`atlas/`:
rubrics, store, ledger, API, Choice history, CLI) · **memory-engineer** (`memory/`: packet,
contextual, shortlist, offers, PR2 demo) · **reader-engineer** (`reader/`, `state.py`,
`session_log.py`) · **lead** (`scoring.py`, `live_gateway.py`, `cli.py`, `jev_client.py`,
docs, all live work) · existing **close-reader** and **skeptical-reader** (one blind pilot
review) · **independent-reviewer** (fresh, read-only). Disagreements that changed the
design: both blind readers vs Jev on bridge for same-speaker pairs → rubric v2; C's trace
found stale-history hands shown as current → memory-currency check; the reviewer found the
unguarded legacy follow route, unledgered Choice retries, and two misleading outcome
sentences → all fixed. All work is uncommitted in the working tree.

---

# Exploration repair, 2026-09-21

The 2026-09-20 handoff reported a complete atlas and passing tests, but everyday browsing
still produced empty results. That handoff was wrong about the product: the requirement
is that **any page × any of the four operators shows at least three destinations you can
preview and follow**, and nothing had tested that in the frontend.

## Reproduced causes (from the user's own records, `data/session_log.jsonl` seq 27–48)

| Observation | Evidence | Cause class |
| --- | --- | --- |
| P1 DEVELOP showed nothing | seq 39: `recorded`, NONE, confidence 0.15 | obsolete single-winner path |
| P6 DEVELOP showed nothing | seq 47–48: new live Choice, NONE 0.14 ("declined all 38 eligible candidates") | obsolete single-winner path |
| PR4 CONTRADICT showed nothing | seq 35–36: new live Choice, NONE 0.41 | obsolete single-winner path |
| PR1 hand: one card | offer set: shortlist of 4 → "1 route qualified of 4 assessed" | global shortlist built before any operator + qualification thresholds |

All four operator buttons still called `/api/request-selection`: one Jev Choice among ~38
candidates **plus NONE**, and an abstention left nothing to browse — while the atlas held
P1→P5 development 0.92 and P6→PR3 development 0.90. Ruled out with evidence: stale server
or frontend (process started after the last edit; served `app.js` sha256 == disk); HTTP
or JS failures (0 responses ≥400 in `data/reader_server.log`); missing or incompatible
atlas data (1,640/1,640 complete); session/policy/cache handling (Discovery correctly
applied in every record).

## What changed

- **`memory/operator_options.py`, policy `operator-options-v1`.** Each operator ranks
  *every* eligible destination with a complete, current-version profile on its own
  dimension (ECHO→echo, DEVELOP→development, CONTRADICT→contradiction,
  BRIDGE→bridge_relation). No provider call. Supported = `score_norm ≥ 2/3` (rubric level
  2); ordered by operator fit, then `direct_q_fit`, then page order; up to 5 supported
  shown. If fewer than 3 are supported, the best remaining are appended, labeled
  **"Exploratory — weak or uncertain fit"**, until 3 are shown. Scores are never altered;
  `low_confidence`, `high_redundancy`, `high_missing_context`, `low_direct_q_fit` are
  descriptive caution chips, never exclusions. Unusable profiles (missing/stale/failed/
  hash mismatch) are listed, never scored as zero. Accessibility (previewable, followable)
  is separate from support (the tier and the number).
- **Reader.** Operator buttons → `GET /api/operator-options` (never dispatches) → ranked
  list with tier badge, fit + confidence, cautions, exact-text preview, Follow.
  `POST /api/follow-option`: same follow-time validation as before; proposal, acceptance
  and Q traversal recorded separately with `operator`, `tier`, `operator_fit`,
  `option_set_id`, `proposal_kind: "operator_option"`. Following an exploratory option is
  recorded as the reader's explicit choice and writes no review or judgment.
- **History refinement is optional and resilient.** `POST /api/refine-options` assesses
  exactly the displayed options against the reading history; it never removes an option
  and never changes a tier; candidates within 0.15 on `works_after_history` keep base
  order (measured rerun noise ≤ 0.10). The ordering line says "base atlas assessments" or
  "your reading history (N encounters supplied)". Error, timeout, budget refusal, or a
  wrong-model answer keeps the base list and says it was *not* newly assessed; retry works.
- **Research path kept, demoted.** "Ask Jev for a single pick (research)" is the old Choice
  request; its abstentions and errors stay recorded and listed and never hide the options.
  The cross-operator hand moved to a collapsed "Advanced" block.
- `GET /api/build` + a footer show the git revision, dirty flag and `app.js` hash.

Atlas-level coverage (`gibsey operator-coverage`): 164/164 combinations show ≥3 under both
policies. Pages needing exploratory fill — discovery: ECHO 2, DEVELOP 3, CONTRADICT 39,
BRIDGE 1. **CONTRADICT is exploratory almost everywhere**: only 1% of pairs reach the
contradiction floor. That is the atlas's honest reading, shown as such.

## Verification of the repair (three kinds, reported separately)

**Tested build:** git `d5e178cae2ec6f30ff1788a466372e2be585143b`, clean tree, `app.js`
sha256 `b6e47a33193d1aa2…`. The restarted reader on 127.0.0.1:8765 reports the same
revision and hash at `/api/build` (also shown in the page footer). Application code is
identical to `2b533ab`; `d5e178c` only fixes the acceptance harness.

**1. Browser coverage using recorded data** — `tests/acceptance/run_browser_acceptance.py`,
headless Chrome via Playwright, isolated instance (temp session; real live atlas
read-only; port 8765 and the real session never touched). Report:
`data/verification/browser_acceptance/20260921T040357Z_d5e178cae2_discovery.json`.
**164 / 164 page × operator combinations passed.** For each: the operator control works;
≥3 distinct, eligible, visible rows; ids, order and tier equal an **independent ranking
computed from `assessments.jsonl` without importing the application**; the displayed fit
and confidence equal the recorded numbers; tier label text exact; every displayed
destination resolves; every preview equals the vault file text; one option followed
(rotating position — 43 of the follows were exploratory rows) and the reader showed the
destination's recorded text; Back returned. 45 combinations contained exploratory rows.
Session log afterwards: exactly the 164 follows, each `operator_proposed → offer_accepted
→ accept_and_follow → q_traversal → page_viewed`, strictly increasing `seq`. 0 console
errors. An earlier run of this harness against `2b533ab` failed 151/164 because of two
defects in the harness's own new checks (vault filenames containing a space; score
compared as a string); that report is kept beside the passing one.

**2. Failure scenarios tested with MOCKS** (same harness; mocks are named and switchable in
`tests/acceptance/serve_isolated.py`): 10 / 10 passed — switching operators while a
refinement is pending; navigating away before the response; double-click refine (exactly
one dispatch per option) and double-click Follow (one traversal); refresh (no dispatch);
provider error → base order kept, explicit wording, retry succeeds; provider timeout →
same; every history answer at the weakest level → all options kept, tiers unchanged,
visible line says the order did not change and that no support was found; single-pick
NONE → ranked options untouched; new browser context restores the page without
dispatch; repeated encounters of the same page.
Independent QA (fresh agent, its own Playwright scripts and its own ranking from the raw
records): 232 page×operator checks over both policies, 1,013 fit cross-checks, 1,013
preview comparisons, 232 follows (60 exploratory), 22 abuse scenarios, zero provider
dispatches on click/load/refresh, no mislabeled tier, no review or judgment written by
any follow. It **confirmed two failures**, both then fixed: unreadable dark-scheme text
(criterion box 1.72:1 — now theme tokens with a test enforcing ≥4.5:1 in both schemes),
and a refinement that changed nothing being described as a reading-history ordering. It
also caught: "moderate" appearing on both tiers, success-green on all-exploratory lists,
second-tab advice that moved the reader, and that the lead's first harness was circular
(it compared the frontend with the same function the server calls) — the harness now
uses the independent oracle.

**3. Interactions verified through real Jev calls** — 8 attempts of the 12 allowed, on a
scratch session, counted on the milestone ledger (1,678 → 1,686; 0 failed; jev-1.13.0;
records in `data/verification/livecheck_20260921_options/`): P1 DEVELOP after P3 (5
supported options) and P6 CONTRADICT after P3→P1 (3 exploratory options) were refined;
tiers and labels unchanged; tie band respected; a repeat was served from cache with 0
attempts. Ledgers now: milestone 1,686 / 2,000 attempts, 5,138,253 tokens; reader ledger
as recorded by `gibsey live-usage`.

**Not verified:** Firefox/Safari; narrow viewports; keyboard-only use; real provider
timeouts (only mocked); light-scheme contrast in a browser (token test only, pending the
QA re-check below).

**How to re-run:** `.venv/bin/python tests/acceptance/run_browser_acceptance.py`
(`--policy include-adjacent`, `--scenarios-only`, `--pages P1,P6`, `--headed`). Needs
`pip install -e '.[dev]'` and a local Chrome; makes no live calls. Data-level check
without a browser: `gibsey operator-coverage`.
