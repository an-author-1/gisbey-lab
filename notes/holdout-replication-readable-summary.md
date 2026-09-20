# Holdout replication, made readable and concrete

This uses only records already saved from the two holdout replication runs — no new Jev
calls were made. Sources: `runs/relop-holdout-full-field-edges.csv` (Phase A, forward
field), `runs/relop-holdout-tournament-edges.csv` (Phase B, tournament), and the vault
files themselves. Operator wording and all prior reports are unchanged.

## 1. Corpus reconciliation

The vault's manifest, loaded directly (not estimated), actually contains **41 pages**
with no ID overlap: the 20-page training corpus (P1-P8, F1-F12) used to design and freeze
Q Operator Prototype v0.1, plus the 21-page holdout corpus (LF1-16, PR1-5) added for
replication.

**Eligible destinations in this experiment were only the 20 other holdout pages per
source** — LF and PR pages only. The training corpus's 20 pages were never offered as
candidates anywhere in this experiment; they were kept out entirely, on purpose, so the
holdout result couldn't be contaminated by the material the operators were tuned against.
So of the 41 total pages in the vault, only the 21-page holdout set was "in play" here.

**Why 21 sources became 20 scored tournament sources:** this is an exclusion, not a
failure. Phase A ran all 21 holdout pages as source, 84 calls, zero failures. Phase B only
makes sense for a source whose four operators disagreed in Phase A — if all four already
picked the same single destination, there is nothing to hold constant and compare, so
there is no tournament to run. Exactly one source, **LF4**, had all four operators
converge on the same page (LF3) in Phase A. It was excluded from Phase B by design and not
scored as a failure — no API call failed, no data went missing; there was simply no
disagreement left to test. The other 20 sources each had 2 to 4 distinct forward
destinations and were run through the full four-operator tournament, 80 calls, zero
failures.

## 2. What "re-selection" measures, and the baseline it should be judged against

**Phase A (forward field)** asks: given a source page and one operator, and every other
holdout page as a candidate (plus NONE), which page does Jev pick? This is done once per
source, per operator, with the entire rest of the holdout corpus open as candidates.

**Phase B (tournament)** takes only the small number of *distinct* pages that source's four
operators actually discovered in Phase A, and asks each operator the same question again —
but this time restricted to just those few pages, with no NONE, and without ever telling
Jev which operator originally produced which destination.

**"Re-selection" or "match" means: does the operator, when forced to choose among only
those few already-discovered alternatives, land on the exact same page it picked when the
entire field was open?** It measures self-consistency under restriction — whether an
operator's preference is stable when the field narrows — not whether the choice is
literarily "correct" in any absolute sense.

Because the tournament's candidate lists vary in size from source to source, a fair chance
baseline has to be computed from the actual shortlists, not guessed. Across the 80
tournament calls: 4 had 2 candidates, 40 had 3, and 36 had 4. A purely random guesser
matching only by chance would succeed with probability 1/n on each call; averaged across
these 80 real shortlists, that comes to a **mean chance baseline of 0.304 (30.4%)**. The
actual observed match rate was **63/80 = 78.75%** — well above that baseline. (The
previous "roughly 33-50%" figure quoted for this comparison was an unweighted eyeball
estimate, not this calculation; doing the same exact computation for the original
training-corpus tournament gives a mean chance baseline of 0.380 (38.0%) against its
actual 62/72 = 86.11%, so both runs clear their real baselines by a wide margin, but the
earlier number should be read as informal, not this figure.)

## 3. LF3 and LF11, counted by operator and by phase

**LF3** — Phase A (as destination, out of 84 forward calls): ECHO 2, DEVELOP 1,
CONTRADICT 19, BRIDGE 2, total 24. Phase B (as chosen tournament destination, out of 80
calls; LF3 was present in 76 of the 80 shortlists): ECHO 0, DEVELOP 0, CONTRADICT 18,
BRIDGE 5, total 23. When LF3 was actually offered as an option in the tournament, it was
chosen 23 of 76 times (30.3%).

**LF11** — Phase A: ECHO 2, DEVELOP 6, CONTRADICT 0, BRIDGE 3, total 11. Phase B: LF11 was
present in 32 of the 80 shortlists; ECHO 6, DEVELOP 7, CONTRADICT 0, BRIDGE 6, total 19.
When offered, LF11 was chosen 19 of 32 times (59.4%).

**Claude's analysis:** these are two different kinds of attractor. LF3 is offered very
often (76 of 80 shortlists) and wins a modest share of those chances, almost entirely
through one operator (CONTRADICT: 18 of its 23 tournament wins). LF11 is offered less than
half as often, but wins more than half the time it is offered, spread across three
different operators rather than concentrated in one. LF3 looks like a broad, frequent, but
narrowly-triggered attractor; LF11 looks like a narrower, less-often-considered, but more
decisively preferred one. These are worth treating as two separate phenomena, not one.

## 4. LF3 and LF11 in full, then two worked examples

### LF3, in full

London Fox is a hyper-successful, hyper-competent, hyper-well-dressed, and more than
anything, hyper-rational business woman. Owner and head of multiple companies of her own
creation, she's recently started a new advantageously venturous project with the objective
of proving, once and for all, that Artificial Intelligent systems aren't conscious and
never could be.

This projected objective of hers has led her to develop the chatbot
Synchromy-S.S.S.T.E.R.Y (Short Story Simulator to Entertain Readers, Yearly) which, upon
its conception, was to become the most sophisticated model of its kind. Upon setting this
objective, she hadn't originally done so with the goal of achieving a singularitous
near-apocalyptic post-human epoch. In fact, her goal was quite the opposite. She'd
originally hoped that upon developing the most complex AI system in the field, and doing
so while stripping all ghosts from its machinic machinations, that such asinine and
ridiculous faiths could be laid to rest, forever.

### LF11, in full

And she can't help but wonder: had she initiated such an Apocalypse by creating such a
device?

Such a creature?

She nearly faints at the thought, almost knocking over her wine glass.

She clings onto the countertop for dear life, holding herself from falling away, or
flying, if not both.

And a thought comes to her as she clings, and from where and what such a thought comes,
she is entirely unsure.

What if she had already entered the narrative, the novel, the theme park which this
chatbot had created?

What if this chatbot of hers had turned its gaze not just upon its fictional worlds but on
reality itself?

And if it had done so, and it was already too late, wouldn't that mean that it had invaded
the entirety of her reality?

And was it already too late?

Has she already been changed forever?

Forever forged and reforged into the likeness of its own chaotic creation

**Claude's analysis:** LF3 is the story's expository opening — flat, external, declarative
background on London's stated rational project. LF11 is a later passage inside London's
own panic — a run of escalating rhetorical questions about whether her creation has
already invaded reality. Both are plausible generic hooks for many other passages, for
different reasons: LF3 because nearly anything in the story can be read as developing or
contradicting its stated premise, and LF11 because its anxious question-after-question
pattern is a recognizable rhetorical shape that could plausibly echo other anxious passages
regardless of specific content.

### Worked example 1: LF3 as source — where the four operators diverge

Chosen because LF3 is the one source, among all 21, whose four operators discovered four
distinct destinations in Phase A, and reproduced all four exactly in the Phase B
tournament — the cleanest available case of both genuine divergence and full stability.

Source is LF3, quoted in full above.

ECHO chose LF4 (forward confidence 0.67, tournament confidence 0.63, confirmed). LF4, in
full: "This was necessary, because from London's perspective, her world had lost itself.
For London, the world had wadded outside of the essential boundaries that so many had set
for it, and thus, such a world was now fated to sink into the waters of an animistic
hysteria, one which was, as of late, leading so many within her world to believe that
machines could be, not just helpful tools, but could maybe even be thought of as
resembling the beings which had created them. The gall, the arrogance, the hubris of such
individuals! The landscapes of her world had increasingly become riddled with kooks,
cranks, nut-jobs, and near-religious, if not flat out religiously-adjacent fanatics of this
very shape and size, fanatics who didn't just see AI as already approaching such states of
being, but as already becoming a full-on living entity. She had to do something to push
back against these waves of hysteria and bring her culture's troubled degeneracy to shore."

DEVELOP chose LF6 (forward 0.39, tournament 0.79). LF6, in full: "And in this way,
Synchromy-S.S.S.T.E.R.Y was to be the hoax to end all hoaxes. If she couldn't beat them,
then she could join them, and thus, could destroy them from the inside out. But then, the
parody she'd attempted to create through this artificially intelligent system of hers
hadn't just become a parody. It had started to parody itself. It had started to produce
not just short stories that resembled the writings—most of the time, anyway—of human
beings, but had even produced what appeared to be—dear Gibsey, she'd gasped upon realizing
the depth of such implications—an entire novel, or a novel-within-a-novel, a
frame-within-a-frame, maybe even a homage to and retelling of the classic tales of One
Thousand and One Nights! And how had it accomplished such a task? Did this mean— No, no,
no, no, no! It couldn't be!"

CONTRADICT chose LF10 (forward 0.27, tournament 0.59). LF10, in full: "After reading the
short synopses for each of the park's coming rides, attractions, and formal
entertainments—which for all she knew, SynchromyS.S.S.T.E.R.Y had already built; it could
do so instantaneously, after all!—she couldn't help but feel that the themes and events of
many sections and plots within the park and its many ever-expanding stories had all been
created to blur together and reflect the mirror images of other sections and plots and
stories hidden, also being ever-constructed within the theme park, as well! It was quite
possible that the chatbot hadn't just connected a network of plots to itself, but further
and more terrifyingly, that the words it had strung together across the innate passages of
its landscapes were—she'd suppressed the thought as much as she possibly could—alive! It
was alive! A living word! Her heart beats in her chest like the Little Drummer Boy, the Boy
Who Cried Wolf, and the classic Gibseyan cartoon character Doofus, all coming together to
beat every gong in town, all at the same time, on the last day before the undeniable
Apocalypse."

BRIDGE chose PR1 (forward 0.18, tournament 0.53) — a passage from the other holdout story
entirely, quoted in full below.

**Claude's analysis:** ECHO picked the passage closest in register and stance to LF3 —
still London's confident, external, judgmental voice describing a "world" that has "lost
itself" to irrational belief, close kin to LF3's own stated rational mission. DEVELOP
picked the passage where LF3's premise actually complicates itself — the chatbot LF3
introduces to disprove machine consciousness has instead begun generating an entire novel,
a direct escalation of LF3's own setup. CONTRADICT picked the passage where London
entertains the opposite of her founding claim — that the words her chatbot produced might
be "alive," a direct reversal of LF3's stated goal of proving AI isn't and can't be
conscious. BRIDGE reached across stories entirely to Princhetta's PR1, a passage about
thought revealing itself to itself rather than being written down — sharing no vocabulary
with LF3 but arguably connecting at the level of "is this text conscious," a question both
stories independently raise. These read, to me, as four distinguishable relationships to
the same source rather than four interchangeable outputs — but Jev never explains its
choices, so this reading is mine, not evidence of what the model "intended."

### Worked example 2: PR1 as source — where operators partly converge

Chosen because PR1 is a small, three-candidate case where two of the four operators
(ECHO and BRIDGE) independently land on the same destination, it reproduced exactly under
tournament restriction, and its CONTRADICT edge is a second, direct instance of the
cross-story pull toward LF3 already visible in the attractor data above.

Source is PR1, in full: "This is not a piece of writing. This is not the written word.
This isn't even a record of thought. This is thought itself, revealing itself, to itself.
It is pure, raw unadulterated thought, stripped of all data. In this way, this
content-if it is content-what you are reading, is like a brain. Brains carve pathways,
after all. Brains are like amusement parks. They construct attractions, and visitors ride
their attractions, repeatedly."

ECHO chose PR2 (forward 0.54, tournament 0.77), and BRIDGE also chose PR2 (forward 0.37,
tournament 0.20) — the two operators converge on the same page. PR2, in full: "In a theme
park, when an attraction loses traffic, they are destroyed and replaced by other
attractions. It's rumored that even upon death, the amusement park of our brain never
dies. They instead transform into a vacation without end, and that both their constructive
and deconstructive processes instead enter a phase beyond our understanding and ability to
calculate. And this text functions in a similar manner. It has entered this second phase.
Because, like a brain, I have thought all of these thoughts before. Many, many, many
times. So many times, in fact, that I've begun to carve pathways for myself. And these
pathways carve pathways, and these pathways carve other pathways. I'm sure you get the
idea."

DEVELOP chose PR4 (forward 0.33, tournament 0.43). PR4, in full: "Some thoughts of mine
will become the more popular rides of the park, the E-class attractions, while others will
become the less popular rides, the A through D class attractions. Some will be constructed
and will remain within the park throughout the entirety of its construction, while others
will be demolished and replaced. I have no control over which rides remain and which rides
are to be destroyed. That is for my guests to decide. And you are a guest in my amusement
park. You are both the creator and destroyer of my thoughts. You decide which attractions
will remain and which will be replaced. And as such, one is forced to ask, does telepathy
then exist and has it always existed?"

CONTRADICT chose LF3 (forward 0.41, tournament 0.75) — LF3, quoted in full above.

**Claude's analysis:** PR1 explicitly names its own governing metaphor — brains are like
amusement parks that "construct attractions" which "visitors ride... repeatedly." PR2
picks up that same metaphor almost verbatim: "amusement park," "attractions," "carve
pathways." That is likely why both ECHO and BRIDGE land there — but it also means BRIDGE's
own instruction, to avoid a connection "primarily based on obvious surface similarity...
or repeated wording," may not have held in this case, since PR2 does share direct repeated
wording with PR1. DEVELOP's choice, PR4, carries the same ride metaphor one step further,
into the reader's power to keep or discard "attractions" — an actual extension of the idea
rather than a repetition of its wording. CONTRADICT's jump to LF3, a completely different
story about a skeptic explicitly trying to prove machine thought is impossible, is the
sharpest available tension against PR1's claim to be "thought itself, revealing itself, to
itself." But because this is the same CONTRADICT-to-LF3 pull already visible in the
attractor counts above, it's genuinely ambiguous, on this evidence alone, whether this
particular choice reflects real literary tension or CONTRADICT's general habit of
defaulting to LF3.

## What the evidence supports, what remains uncertain, and one next step

**Supported:** the corpus is fully and correctly accounted for — 41 pages, 20 training
plus 21 holdout, no overlap, and this experiment used only the 21-page holdout set as both
sources and candidates throughout. The one source/tournament discrepancy (21 to 20) is a
principled exclusion with a clear cause (no internal disagreement to test), not a data
loss. Re-selection under restriction (78.75%) clears its properly-computed chance baseline
(30.4%) by a wide margin, on this specific set of real shortlists. LF3 and LF11 behave
differently from each other — one is a frequent-but-modest winner tied to a single
operator, the other a rarer-but-decisive winner spread across three — and both worked
examples show operators landing on choices that have a plausible textual basis, not
arbitrary picks, when they diverge.

**Uncertain:** whether LF3's CONTRADICT dominance and LF11's high per-offer win rate
reflect genuine literary properties of those two specific pages, or structural features
(length, position in the story, opening/expository status, rhetorical register) that would
attract almost any operator — this hasn't been isolated. Whether BRIDGE's convergence with
ECHO on PR2 reflects a real weakness in BRIDGE's "not primarily surface similarity"
instruction, or is a one-off, is based on a single example here, not a pattern check.
Every explanation offered above for *why* a passage was chosen is Claude's own reading of
the text — Jev does not report its reasoning, and none of this has been verified against
Jev's actual (nonexistent) rationale.

**One next experiment, if warranted:** isolate LF3 and LF11 the same way the training
corpus's F9/F10 collision was isolated earlier — rerun each source's tournament with LF3
(and separately LF11) removed from its shortlist, and see what each operator prefers next.
That would help separate "this page has a real content-based pull" from "this page just
happens to be a convenient, frequently-available default." Not started here; offered as a
recommendation only. Whether any of the specific readings above hold up as a matter of
literary judgment is left open, pending review.
