# Atlas pilot calibration (2026-09-20)

Status of everything below: **Jev scores are provider output; reviewer levels are agent
interpretations (Claude subagents `close-reader` and `skeptical-reader`), not human
judgments and not ground truth.** Agreement between the two reviewers is not proof. No
human literary judgment is recorded here. The pilot pairs are provisional calibration
examples.

## Procedure

- Pairs: F12↔P8, PR1↔PR4, LF1↔LF3 (both directions, as required) plus two chosen by the
  lead from the corpus: **P7→LF13** (liability disclaimer → London in the dark; expected
  weak) and **P1→PR1** ("I didn't write this. This is a found text" → "This is not a piece
  of writing"; ambiguous between echo and contradiction).
- Jev: one request per directed pair, seven independent Score questions,
  `atlas-rubric-v1`, requested `jev-latest`, returned `jev-1.13.0`, config not frozen.
  Job `atlas-live-20260920T190417Z-110072`. 8 attempts, 0 retries, 23,425 reported input
  tokens (≈2,930/request). Records: `data/atlas/assessments.jsonl`.
- Reviewers: each read one packet containing only the rubric text and the exact passages.
  Neither saw Jev scores, the other reviewer, or the repository. Each was asked for a
  level 0–3 per dimension with quotations for any level ≥2, and for rubric weaknesses.

## Levels side by side (Jev expected score 0–3 · close reader · skeptical reader)

| pair | direct_q_fit | echo | development | contradiction | bridge_relation | redundancy | missing_context |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F12→P8 | 2.55 · 2 · 2 | 2.93 · 3 · 3 | 2.07 · 1 · 1 | 0.56 · 1 · 1 | 2.30 · 1 · 1 | 0.62 · 1 · 1 | 0.69 · 1 · 1 |
| P8→F12 | 2.69 · 3 · 2 | 2.94 · 3 · 3 | 2.65 · 2 · 2 | 0.75 · 1 · 1 | 2.34 · 1 · 1 | 0.61 · 1 · 1 | 1.92 · 2 · 2 |
| PR1→PR4 | 2.99 · 3 · 3 | 2.97 · 3 · 2 | 2.81 · 3 · 2 | 0.39 · 2 · 1 | 1.37 · 0 · 0 | 0.84 · 1 · 1 | 0.61 · 0 · 0 |
| PR4→PR1 | 2.88 · 2 · 2 | 2.84 · 2 · 2 | 2.79 · 2 · 1 | 0.64 · 1 · 1 | 2.79 · 0 · 0 | 1.23 · 1 · 1 | 0.16 · 0 · 0 |
| LF1→LF3 | 1.83 · 2 · 2 | 1.06 · 1 · 1 | 1.76 · 2 · 1 | 0.39 · 1 · 1 | 2.10 · 0 · 0 | 0.13 · 0 · 0 | 0.45 · 0 · 0 |
| LF3→LF1 | 2.28 · 2 · 2 | 1.78 · 1 · 1 | 2.27 · 2 · 1 | 1.86 · 2 · 2 | 1.62 · 0 · 0 | 0.17 · 0 · 0 | 1.38 · 2 · 1 |
| P7→LF13 | 1.93 · 1 · 0 | 0.93 · 0 · 0 | 1.85 · 1 · 0 | 1.10 · 1 · 0 | 2.40 · 2 · 1 | 0.02 · 0 · 0 | 1.38 · 2 · 2 |
| P1→PR1 | 1.68 · 3 · 2 | 1.52 · 3 · 2 | 1.36 · 2 · 1 | 2.20 · 2 · 2 | 2.21 · 2 · 2 | 0.05 · 1 · 0 | 0.20 · 0 · 0 |

## What the comparison shows

- **Direction is carried.** Jev and both reviewers agree that missing context is higher
  P8→F12 than F12→P8 (F12 leans on "Imaginator", "AGI and Gibsey Vault", "hologic
  transition"), and that contradiction is higher LF3→LF1 than LF1→LF3 ("more than
  anything, hyper-rational" undercut by "Won't believe it").
- **Echo and redundancy separate.** The verbatim closing edict ("Keep your hands, arms,
  feet, and legs inside the vehicle…") gives echo ≈3 with redundancy ≈1 in all three
  readings.
- **Concrete defect — `bridge_relation` v1.** On the four same-speaker / same-conceit
  pairs both reviewers read 0; Jev returned 1.37–2.79. The cause is visible in the
  wording, independent of the reviewers: level 0 joined two unrelated conditions ("same
  context" OR "nothing connects") while Score evaluates each level description on its own,
  and levels 2–3 accepted a difference in "situation, characters, *or* conceptual
  context". → **One revision, `atlas-rubric-v2`**: bridge only; difference of
  speaker/characters *and* situation is required at levels 1–3, level 0 is solely "nothing
  to bridge", level 1 absorbs "only vocabulary/setting/general theme/very abstract
  likeness". v1 stays importable; v1 pilot records stay on disk and read as stale.
- **Known leniency, deliberately not tuned.** On the intended-weak pair P7→LF13, Jev sits
  about one level above the reviewers on direct_q_fit (1.93 vs 1/0) and development
  (1.85 vs 1/0), with low confidence (0.42, 0.34). On the ambiguous pair P1→PR1 Jev is
  *lower* than the close reader on direct fit and echo. These are differences of reading,
  not integration defects, and were left alone to avoid tuning toward preferred winners.
  Practical consequence: shortlist floors should not treat ~1.9/3 as strong support.

## Rubric weaknesses the reviewers reported (recorded, not all acted on)

1. bridge levels too easy to reach via "or conceptual context" (both) — **fixed in v2**.
2. echo "structure" and bridge "common structure" can credit the same feature (both).
3. development level 3 "re-framing" shades into contradiction level 2 "undercuts" (both).
4. direct_q_fit has a practical floor of 1 for same-book pairs; level 2's "link the reader
   must supply" is reachable by a motivated reader (skeptical).
5. contradiction has no level for "specific claim engaged, mildly" (skeptical).
6. development: later backstory always "changes how the source can be understood";
   no slot for illustrating a consequence without sharing the subject (both).
7. echo: formulaic boilerplate reaches 3; recurring proper names unaddressed; level 3's
   "prominently or more than once" makes recurrence direction-dependent (both).
8. missing_context: gap between "one or two" terms and "important part"; deliberate
   withholding vs real dependence not separable (both).

Items 2–8 are left as documented limitations of `atlas-rubric-v2`. The configuration is
frozen after the v2 re-pilot; further rubric work is a new version, not an edit.
