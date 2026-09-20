# Q Operator Prototype v0.2

Frozen v0.1 (`notes/q-operator-prototype-v0.1.md`) is unchanged and remains fully
inspectable; its historical runs and results are untouched. v0.2 is the reader's active
version for new requests. Both versions live side by side in
`src/gibsey_lab/relational_operators.py` (`V0_1_CRITERIA`, `V0_2_CRITERIA`,
`CRITERIA_BY_VERSION`).

## Why

Real usage surfaced a specific weakness: DEVELOP frequently selected the immediate next
authored page. Two examples from the reader's own recorded session (`full-41` field,
v0.1, include-adjacent policy, both live):

* `PR1` / DEVELOP -> `PR2` (confidence 0.37) -- PR2 is PR1's next page.
* `PR2` / DEVELOP -> `PR3` (confidence 0.46) -- PR3 is PR2's next page.

Historical full-field data from both corpora shows the same pattern repeatedly (P1->P2,
F7->F8, F9->F10, LF6->LF7, LF7->LF8, PR2->PR3, PR3->PR4, among others). Ordinary
narrative continuation is a weak, largely positional signal, not evidence of a specific
developed implication -- but v0.1's DEVELOP wording never excluded it.

## What changed

Two independent things address this, and the bounded-sample check (below) tests them
both together and separately:

1. **Discovery candidate policy** (`fields.py`): excludes the source's immediate authored
   predecessor/successor within its own text from the candidate set, so the next/previous
   page literally cannot be selected. This alone forces a non-adjacent choice but says
   nothing about whether that choice is any good.
2. **v0.2 DEVELOP wording**: explicitly excludes "ordinary continuation... or additional
   detail alone" from dominating the choice, asking instead for a specific implication,
   consequence, mechanism, or a change in how the source can be understood.

The other three v0.2 operators were also revised for analogous reasons (see exact wording
below), all preserving NONE and none of them treating cross-collection or distance as an
intrinsic mark of quality.

## Exact v0.2 criterion text

**ECHO:** Select the passage that shares a specific, identifiable textual correspondence
with the source passage -- a phrase, image, structure, or claim that recurs -- where that
return has an identifiable reading effect: something it changes, intensifies, or
clarifies about how the source is understood. A shared topic or vague thematic similarity
alone is not sufficient. Choose NONE if no candidate offers such a correspondence.

**DEVELOP:** Select the passage that extends a specific implication of the source,
introduces a concrete consequence or mechanism arising from it, or changes how the source
itself can be understood. Ordinary continuation of the narrative or the addition of
incidental detail alone should not dominate the choice -- prefer a candidate that does one
of the above over one that merely continues or restates. Choose NONE if no candidate does
this.

**CONTRADICT:** Select the passage that challenges a specific claim, assumption, or
relationship stated or implied in the source passage. Two passages that each separately
express doubt, negation, or disbelief are not automatically in tension with each other --
the challenge must engage the source's specific content, not merely share a register of
denial. Choose NONE if no candidate does this.

**BRIDGE:** Select the passage that establishes a defensible connection between
situations, characters, or conceptual contexts that are otherwise different from the
source's -- a connection explainable in terms of what the two passages are actually
doing, not just words they share. Shared vocabulary or setting alone is not sufficient,
and crossing between different authored texts is not itself a mark of quality. Choose
NONE if no candidate offers such a connection.

## Bounded-sample comparison

See `notes/q-operator-v0.2-bounded-sample.md` for the full comparison (at most 24 live
calls: DEVELOP under v0.1/complete-field, v0.1/Discovery, v0.2/Discovery on four sources
-- one per authored text, preferring real recorded-session examples of next-page
DEVELOP selections -- plus the other three v0.2 operators under Discovery on the same
four sources), including provisional close-reader/skeptical-reader agent assessments.

## Status

v0.2 is active for new reader requests as of this note. Not yet re-validated at
full-field-experiment scale (the earlier 80/72/53-call experiments were all against
v0.1) -- that would be a separate, explicitly scoped future experiment, not implied by
this bounded check.
