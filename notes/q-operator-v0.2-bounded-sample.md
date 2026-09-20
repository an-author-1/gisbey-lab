# v0.2 bounded-sample check

24 live calls (23 fresh, 1 reused from a matching real recorded run), pinned model
`jev-latest` -> `jev-1.13.0` throughout, `full-41` field. No prior record modified; no new
tournament or full-field batch. Sources chosen: one per authored text (P1, F9, LF6, PR2),
each a confirmed historical case where DEVELOP under v0.1 selected the source's immediate
next authored page. PR2 additionally comes from the reader's own real session
(`PR1 -> PR2 -> PR3`, both real DEVELOP-picks-next-page instances).

## DEVELOP across three conditions

| Source | v0.1, complete field (include-adjacent) | v0.1, Discovery | v0.2, Discovery |
| --- | --- | --- | --- |
| P1 | **P2** (0.36) — next page | P3 (0.39) | **NONE** (0.15) |
| F9 | **F10** (0.47) — next page | F1 (0.31) | F12 (0.08) |
| LF6 | **LF7** (0.39) — next page | LF11 (0.25) | LF8 (0.22) |
| PR2 | **PR3** (0.46) — next page, real session | PR4 (0.41) | PR4 (0.29) |

Bold = the confirmed next-page pick that motivated this check. In all four cases,
Discovery alone (still v0.1 wording) already forces a non-adjacent choice, as designed.
v0.2 wording then does one of three different things on top of that: abstains (P1),
picks a different, very-low-confidence destination (F9), or lands on the exact same
destination Discovery-alone already reached (LF6 stays a new pick vs. Discovery's LF11 —
actually differs; PR2 matches Discovery's PR4 exactly). Confidence drops from v0.1 to v0.2
in three of four non-abstaining cases (F9: 0.31->0.08, LF6: 0.25->0.22, PR2: 0.41->0.29),
which reads as the model finding fewer strong candidates under the stricter wording, not
as noise in one direction only.

## Other three v0.2 operators under Discovery, same four sources

| Source | ECHO | CONTRADICT | BRIDGE |
| --- | --- | --- | --- |
| P1 | P5 (0.54) | P6 (0.22) | P3 (0.39) |
| F9 | F1 (0.52) | P1 (0.31) — cross-text | F7 (0.31) |
| LF6 | LF9 (0.37) | LF3 (0.20) | **P3** (0.24) — cross-text |
| PR2 | PR4 (0.38) | **NONE** (0.36) | PR4 (0.27) |

Notable: LF3 and P3 — the two destination attractors identified in the earlier holdout
tournament and reverse-typing experiments — still appear here (LF6/CONTRADICT->LF3,
LF6/BRIDGE->P3, P1/BRIDGE->P3) under entirely new v0.2 wording and the Discovery policy.
That pull looks like a property of those two pages, not an artifact of v0.1's specific
phrasing — worth a dedicated future diagnostic, not resolved here.

## Failures

None. 24/24 calls succeeded (23 live, 1 reused).

## Agent review (provisional, not a human judgment)

Two independent, read-only reviews (close-reader and skeptical-reader; neither saw the
other's output, neither was told confidence) were run on 7 selected traversals: the v0.1
"before" (next-page) and v0.2 Discovery "after" DEVELOP pairs for F9, LF6, and PR2 (P1 is
excluded from this part since v0.2 abstained — there is no destination pairing to review),
plus the LF6 BRIDGE -> P3 cross-text pairing as an additional check. Full agent output,
unedited, is in `notes/q-operator-v0.2-bounded-sample-agent-reviews.md`.

**This is not a clean win.** The skeptical reader found real, text-grounded doubts about
several v0.2 picks, not just the v0.1 ones — a nonadjacent selection is not being treated
as success on its own, per instruction.

**F9 -> F10 (v0.1, next page) vs. F9 -> F12 (v0.2), the weakest/least resolved case:**
the close reader found structural naming in F10 ("Table of Contents," "Gibsey Vault,"
"AGI") for F9's vague task list, and a builder/rider dual role in F12 ("Imaginator...
park goer") that F9 never states. But the skeptical reader flagged both as leaning on
recycled phrasing rather than complication — F10 repeats "Gibsey Vault" and "in medias
res" nearly verbatim from F9; F12's back half ("Return to texts often... Keep your hands,
arms, feet, and legs inside the vehicle") is exactly the "incidental detail" v0.2's
wording says shouldn't dominate, with only one sentence really carrying the pairing. F9's
v0.2 result also has the lowest confidence in the whole batch (0.08).

**LF6 -> LF7 (v0.1, next page) vs. LF6 -> LF8 (v0.2):** the close reader found LF7 adds a
generative, self-multiplying mechanism to LF6's shock, and LF8 introduces a distinct named
mechanism (the "F.O.R.E.S.H.A.D.O.W.I.N.G function") shifting from retrospective shock to
prospective dread. The skeptical reader pushed back on both: LF7 mostly intensifies
LF6's own vocabulary ("novel," "stories") rather than complicating it (arguably closer to
ECHO), and LF8's mechanism is followed by a long catalog of unrelated plot premises —
exactly the "incidental detail" v0.2 says shouldn't dominate. Net: v0.2's pick has a real,
named mechanism v0.1's pick lacks, but isn't spotless either.

**PR2 -> PR3 (v0.1, next page, real session) vs. PR2 -> PR4 (v0.2):** the close reader
found PR4 adds a stated selection mechanism (popular vs. unpopular "rides," demolition,
reader control) that PR3 lacks. The skeptical reader agreed PR3 leans heavily on
restating PR2's own repetition motif almost point for point (also arguably closer to
ECHO), but also flagged PR4's closing "does telepathy then exist" as an abrupt pivot not
clearly derived from the mechanism just established. Net: this is the cleanest
improvement of the three DEVELOP pairs — PR4 has a real new mechanism, even if its ending
line is a loose thread.

**LF6 -> P3 (BRIDGE, cross-text):** the close reader read this as a specific shared
literary reference (Scheherazade / One Thousand and One Nights) doing real work — LF6
from outside a self-generating fiction, P3 from inside as a possibly-artificial narrator.
The skeptical reader pointed out this is BRIDGE's own stated exclusion in miniature —
"shared vocabulary or setting alone is not sufficient" — and the clearest link is
precisely a shared proper-noun reference, with both passages already occupying similar
AI-and-1001-Nights territory rather than "otherwise different" contexts. Genuinely
contested between the two reviewers; not resolved here.

**What this suggests, tentatively:** v0.2 does appear to be finding destinations with
more specific, nameable mechanisms than v0.1's next-page defaults (LF8's FORESHADOWING
function, PR4's selection/demolition mechanism) — but "ordinary continuation... alone"
has not been fully eliminated; it just moved from being the dominant textual overlap to a
secondary feature the skeptical reader can still point to in most of these picks. Four
sources under one operator is not enough to call this resolved.
