# Core v0.3 — literary recurrence pilot proposal (2026-09-25)

**Proposed for Brennan's review; not an approved score or an artistic finding.**
The synthetic recurrence demonstration is separate from this proposal and from the
authored corpus. No provider call, new literary assessment, or corpus edit was made
for this investigation. Existing bond wording remains
`wording_source: destination_opening_sentence`.

## Candidate route family

Start at **P1@c8adbba7f4ed**, go outward twice, then return to that exact version:

1. P1 → **DEVELOP** → P5@23fc2364ab4a.
2. P5 → **ECHO** → F11@5729f5fec994; alternatively F5@7c5bde18887b.
3. F11 → **ECHO** or **DEVELOP** → P1; alternatively F5 → **DEVELOP** → P1.

Every listed directed edge is supported by the existing frozen atlas under Discovery
policy. None is an immediate authored neighbor. The existing neutral resolver ranks
P5→ECHO→P1 first; a recurrence score would exclude that tempting immediate return until
the reader has made the second outward arrival. F11 and F5 are currently displayed
P5 ECHO choices, so this contrast does not depend on finding a new relationship.

| Directed edge | Exact bond identity | Existing assessment | Fit / 3; confidence | Bond status at investigation |
| --- | --- | --- | --- | --- |
| P1→P5 DEVELOP | `bond_248987c718f4b6934a8a` | `as-cc43d39d632a4ff7823ba3ba4dda9cbb` | 2.75; 0.75 | Persisted Session 1/2 and reader bond |
| P5→F11 ECHO | `bond_ad4dd39b3a11e05ad12d` | `as-cd3770828743442e99f78c2a34e7fd93` | 2.46; 0.46 | Persisted Session 2 offer |
| F11→P1 ECHO | `bond_9f8d7f350f43817963bd` | `as-83b06f7224854e2abbfd25e0db2ed76d` | 2.69; 0.69 | Deterministic prospective bond, not previously persisted |
| F11→P1 DEVELOP | `bond_c2704d66ca2c38746431` | `as-83b06f7224854e2abbfd25e0db2ed76d` | 2.85; 0.85 | Deterministic prospective bond, not previously persisted |
| P5→F5 ECHO | `bond_30b8cb9cbd09930cdded` | `as-83ef394a7f8741eab5317e306a514f03` | 2.51; 0.51 | Persisted Session 2 offer |
| F5→P1 DEVELOP | `bond_96ec63c1b7dc9e4891b4` | `as-12cd9814dfb747868ba5c008529f89eb` | 2.49; 0.49 | Deterministic prospective bond, not previously persisted |

The prospective identities are computed by the existing `core.identity.bond_version_id`
and `core.core.bond_wording` from these exact endpoint versions and destination opening
sentences. They do not claim a previously published bond or a previously enacted route.
Publication of the closure offers remains a concrete pilot preparation step after review.

Persisted references: `data/core/sessions/s_d09a7820e595/events.jsonl:2` and
`data/verification/core_v03_session2_demo_2026-09-25/core/sessions/s_10169fa2df45/events.jsonl:10`.
Assessment references in `data/atlas/assessments.jsonl`: lines 1165, 1303, 444,
1297 and 204 respectively. The same F11→P1 pair record separately assesses ECHO and
DEVELOP; these are alternative operators, not interchangeable labels.

## Proposed movements and intended effect

Proposed outward movement: two successful Q arrivals at unvisited exact versions,
allowing ECHO/DEVELOP. Proposed return movement: one successful Q arrival at the exact
entry version, with at least **two intervening encounters**. For the listed routes,
entry is index 0 and the candidate return is index 3: index distance is 3, while the
intervening count is 2. Relocations would be unavailable during this short pilot;
an explicit exit would end the performance as exited and permit ordinary reading.
Pause/resume would preserve progress, reader ending would differ from completion,
and absence of an eligible relationship would block with an explanation.

These movement predicates alone admit additional corpus choices. To present only this
small family, an approved pilot would also need a reviewed, immutable allowed-bond
snapshot. This document does not imply that every other outward choice closes legally.
The current proposal checks six edges and three complete three-transition routes;
it is not a broad reachability or reader-experience study.

**Agent's proposed reading, subject to Brennan's judgment:** move from an uncertain
author, through possible authors inside the fiction, to the reader's implication in
authorship; then reread the original denial. The F5 branch instead dwells on the
difference between an author and The Author before returning to the denial.
This is a proposed effect, not evidence that any reader experiences it.

The text inspected directly supports the following observations:

- `vault/an author's preface/P1.md:1`: “I didn't write this.” Line 3 says the original
  author's identity has not been located.
- `vault/an author's preface/P5.md:3`: suspects may be “The Author of these very pages”;
  line 5 enumerates characters among those suspects.
- `vault/The Foreword to the Foreword to an author's preface/F11.md:16` directly tells
  the reader “you are The Author of at least three of the above texts”.
- `vault/The Foreword to the Foreword to an author's preface/F5.md:1` explicitly
  distinguishes being “an author rather than The Author”.

Those short spans were checked in the actual passage files. Their selection and the
route interpretation are this agent's new proposal; they are **not** stored textual
evidence returned by the atlas assessments and have not been reviewed by Brennan.

## Evidence scope and gaps

The pinned source is manifest `man-3a78abbbfbe8e2a23d7e`, config
`cfg-5a7766c6c2012139e7bab61f`, rubric `atlas-rubric-v2`, model `jev-1.13.0`.
Manifest assessment-set SHA-256:
`c9c27d5e046ed8534d284c48b5fa00bda20b71c1325309cfa44379c4b569c0f0`.

Each named record assesses one directed pair from the two supplied exact passage
texts, with seven independent rubric dimensions. It contains scores, probability
distributions, confidence, rubric wording, and request provenance. It contains no
returned passage quotations, human review, or judgment of this ordered three-step
journey. All six proposed edge checks matched both recorded endpoint hashes against
the current passage text. P5→F11 ECHO and F5→P1 DEVELOP have confidence below 0.5;
the support-floor policy admits them, but artistic review should not overlook this.

Remaining gaps: closure bonds have not been published as retained pilot offers;
selected supporting spans are not yet curated assessment evidence; no artist-approved
score, bond wording, or reader-experience evidence exists. No inference about artistic
quality follows from a probability or from successful mechanical execution.

## Investigation commands

- `find .. -name AGENTS.md -o -name CLAUDE.md` and explicit ancestor-file reads found
  no additional applicable project instructions.
- Read `Gibsey_Core_v0.3_Weekend_Plan.md` §§3–6,
  `notes/core-v03-status.md`, baseline audit/contracts, and the Session 2 bundle README.
- `nl -ba` on P1, P5, F5 and F11 verified the quoted locations; inspected P8, F12,
  PR1, PR2, PR3 and PR4 as alternative candidates without changing them.
- An inline `.venv/bin/python` read-only inspection called `load_field('full-41')`
  and `operator_options(..., policy='discovery')` for the candidate sources/operators,
  enumerated journal bonds, computed identities with `bond_version_id`, and verified
  retained source/destination text hashes against the field manifest. It used the
  existing live atlas as frozen input and dispatched no provider request.
- After interruption recovery, repeated the six edge checks using the same read-only
  functions: all six bond identities, support tiers, assessment IDs, endpoint hashes,
  scores, and confidences matched the table. The default P5 ECHO display was
  `[P1, P2, F6, F5, F11]`. Rechecked the four quoted passages with `nl -ba`, the five
  assessment locations with `rg -n`, and the frozen identity metadata in
  `data/atlas/index_manifest.json`; all matched. No source data was written.

## Concrete artistic decision

**Brennan: should the first real recurrence pilot make the reader revisit
“I didn't write this” after the text has implicated the reader as an author, using
P1→P5→F11→P1, with F5 as the more uncertain alternative?** Approve or revise the
intended effect and those alternatives before turning this proposal into an authored
score. Bond-wording replacements remain a separate approval; all present wording
stays labeled `destination_opening_sentence`.
