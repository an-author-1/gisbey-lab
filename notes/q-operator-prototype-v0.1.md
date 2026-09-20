# Q Operator Prototype v0.1 (frozen)

This freezes the four relational operators developed and tested across the original
20-page corpus (`vault/an author's preface/` + `vault/The Foreword to the Foreword to an
author's preface/`), as of the tournament experiment. Wording is now version-pinned; do
not change ECHO, DEVELOP, CONTRADICT, or BRIDGE below without minting a new version
(v0.2+) and re-running the affected experiments. This file is the reference for that
wording going forward — other notes should point here rather than restating it.

## Frozen criterion text (verbatim, unchanged since introduction)

**ECHO:** Select the passage that most strongly returns to, mirrors, resonates with, or
meaningfully recurs from the source passage. Choose NONE if no candidate offers a
meaningful echo.

**DEVELOP:** Select the passage that most productively extends, complicates, develops, or
transforms what the source passage is doing. Choose NONE if no candidate offers a
productive development.

**CONTRADICT:** Select the passage that most meaningfully resists, reverses, destabilizes,
challenges, or creates tension with the source passage. Choose NONE if no candidate creates
meaningful tension.

**BRIDGE:** Select the passage that creates the strongest useful connection to the source
that is not primarily based on obvious surface similarity, repeated wording, or direct
thematic overlap. Choose NONE if no candidate offers such a connection.

Model: `jev-1.13.0` (pinned explicitly across every experiment below).

## What v0.1 is backed by

| Experiment | Calls | Report |
| --- | --- | --- |
| Full-field forward selection (20 sources x 4 operators, canonical order) | 80 | `notes/relational-operators-full-field.md` |
| Operator-conditioned destination tournament (18 testable sources x 4 operators, restricted candidate set) | 72 | `notes/relational-operators-tournament.md` |
| Reverse operator typing (53 unique forward pairs, post-hoc labeling) | 53 | `notes/relational-operators-reverse-typing.md` |
| Earlier 4-source / 2-order pilot, collision/BRIDGE diagnostics | 24 + 12 | `notes/relational-operators-experiment.md`, `notes/relational-operators-diagnostic.md` |

## Frozen findings (exact figures, as instructed)

* Full-field forward selection: **80 calls**, 0 failures, 0 NONE, model `jev-1.13.0`
  throughout.
* Tournament re-selection: **62/72 = 86.1%** overall.
* **12/18** testable sources (2+ unique forward destinations) achieved exact 4/4
  tournament reproduction.
* Per-operator tournament re-selection: **ECHO 17/18, BRIDGE 17/18, DEVELOP 14/18,
  CONTRADICT 14/18.**
* **F12 reproduced all four distinct destinations exactly** (ECHO->P8, DEVELOP->F4,
  CONTRADICT->P6, BRIDGE->P3), all four matching its original forward-field picks under
  restricted head-to-head competition.
* Reverse multiclass typing **failed**: DEVELOP absorbed **49/53 (92.5%)** of post-hoc
  labels; BRIDGE was recovered in **0/11** singleton pairs (always relabeled DEVELOP).

## Working conclusion (frozen alongside the wording)

**These four operators should currently be treated as traversal/selection operators —
functions that steer a choice among live candidates — not as mutually exclusive
retrospective edge labels.** They discriminate well (tournament) when comparing plausible
alternatives, but do not survive being independently re-identified from an already-fixed
pair (reverse typing). Any future QDPI use of these operators should route through
selection among candidates, not through post-hoc classification of an existing edge, until
that finding changes.

## Status

**Frozen as of this note.** No wording changes are authorized without minting v0.2 and
re-running the full-field + tournament experiments against the new wording. All prior data
and experiment reports referenced above are unmodified and remain the v0.1 evidence base.
