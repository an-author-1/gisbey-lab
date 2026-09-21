# Gibsey Lab — Relationship Atlas + Reader Memory Milestone

Implement the next Gibsey Lab milestone using the relationship-and-memory reset document I just added to this repository.

You are starting a fresh Claude Code session. Recover the project's actual state from the repository. Do not assume access to previous conversations.

This is an **implementation assignment**. Inspect, build, test, run the bounded live work described below, and leave me a usable reader.

Do not stop after producing another plan, architecture memo, scaffold, or set of recommendations.

---

# 0. USE AN AGENT TEAM FOR THIS ASSIGNMENT

This milestone is intentionally suited to parallel investigation.

If Claude Code Agent Teams are available, create and coordinate a team.

If the exact Agent Teams feature is unavailable in this environment, approximate the same structure using subagents and isolated git worktrees where appropriate.

The primary Claude session is the **lead / integrator**.

The lead should delegate independent investigations and implementation tracks, keep ownership boundaries clear, compare findings, integrate compatible work, run final verification, and leave the repository in a coherent state.

Do not simply spawn several agents to edit the same files simultaneously.

## Initial team

After the lead performs enough repository reconnaissance to understand the actual project layout, create agents roughly along these responsibilities. Adapt names and boundaries to the real architecture you discover.

### Agent A — Repository Archaeologist / Data Auditor

Investigate:

* current repository architecture
* existing atlas or relation data
* experiment records
* corpus identities and hashes
* cache structures
* Jev/mock separation
* Discovery policies
* previous full-field runs
* existing coverage
* session-history format
* PR1→PR3→PR2 provenance

This agent should primarily investigate and report before editing.

Its job is to answer:

> What already exists, what is reusable, what is stale or incompatible, and exactly what data is actually missing?

Do not infer coverage from API-call counts.

---

### Agent B — Relationship Atlas / Jev Engineer

Own the base pair assessment system and Jev integration.

Investigate and implement:

* seven-dimensional pair profiles
* versioned rubrics
* directionality
* compatibility/reuse rules
* provider request structure
* resumable atlas builds
* request/token accounting
* coverage reporting
* model/version recording
* failure/stale/unassessed distinctions

This agent should also verify current official Jev/TypeSafe documentation before changing the adapter.

---

### Agent C — Reader State / Memory Engineer

Own the distinction between:

**page graph**

and

**reader-state graph**.

Implement:

* versioned memory packets
* encounter history
* back-navigation semantics
* contextual cache keys
* history-conditioned assessments
* deterministic candidate shortlist construction
* contextual route judgments
* PR2 comparison fixtures

This agent should explicitly trace how reader history moves from:

session record
→ memory packet
→ provider input
→ contextual assessment
→ route offer.

---

### Agent D — Reader Interaction / State-Machine Engineer

Own the reported reader problems and runtime interaction states.

Investigate and implement:

* `not requested`
* `loading`
* `selected`
* `abstained`
* `no candidates`
* `error`

Also investigate:

* disappearing NONE results
* rerun behavior
* stale responses
* duplicate clicks
* unintended movement
* proposal vs acceptance vs traversal
* eligibility validation at follow time
* preservation of previous outcomes
* manual navigation
* active-page atlas inspection

Avoid unrelated UI redesign.

---

### Agent E — Independent Reviewer / Pathway Analyst

This agent should initially modify nothing.

Its first job is to independently inspect the reset document, corpus structure, current system, and the findings from the other agents.

It should look specifically for:

* conflation between Choice rankings and pair scores
* conflation between base pair data and contextual judgments
* hidden assumptions about literary quality
* cache compatibility errors
* incomplete coverage being described as complete
* history that is recorded but not actually sent to the provider
* weak relationships being coerced into route cards
* accidental implementation of A/L semantics during a Q→Q milestone
* tests that appear to pass without testing the intended behavior
* unsupported mathematical analogies being treated as established architecture

Before final integration, this agent should conduct an adversarial review of the assembled implementation.

---

# 1. TEAM OPERATING RULES

The lead agent owns integration.

Before parallel coding begins:

1. Inspect the repository enough to identify subsystem boundaries.
2. Assign explicit file/subsystem ownership.
3. Use isolated worktrees for agents making substantial independent code changes when supported.
4. Avoid two agents modifying the same files without coordination.
5. Preserve existing data and history.

Agents may investigate in parallel immediately.

Agents may implement independent modules in parallel once boundaries are understood.

The lead should periodically gather findings and adjust assignments.

Do not let agents independently redesign the application.

The reset document and QDPI master matrix remain authoritative.

## Parallel reasoning is especially encouraged

When an architectural choice is uncertain, do not immediately commit to the first plausible solution.

Have multiple agents independently trace the relevant pathway.

Examples:

### Atlas pathway

authored page
→ immutable version
→ ordered pair
→ seven-dimensional base profile
→ stored provenance
→ candidate eligibility

### Reader-memory pathway

encounter
→ session event
→ ordered history
→ memory packet
→ contextual provider request
→ assessment
→ offer

### Runtime pathway

current page
→ atlas shortlist
→ history-conditioned judgment
→ qualified offer
→ proposal
→ acceptance
→ Q traversal
→ new reader state

### Data provenance pathway

provider request
→ exact supplied text/context
→ returned model/version
→ raw result
→ distribution/confidence
→ validation
→ persisted record
→ cache compatibility

Agents should compare these pathways for contradictions before implementation is considered complete.

---

# 2. RECOVER CONTEXT AND ESTABLISH SCOPE

Read applicable:

* `CLAUDE.md`
* `AGENTS.md`
* Git status
* recent Git history
* README
* dependency files
* corpus manifest
* existing implementation
* experiment records

Locate and read:

* `Gibsey_Lab_Relationship_and_Memory_Reset.md`, or the document titled **Gibsey Lab: Relationship and Memory Reset**
* the QDPI master function matrix

Find the reset document by title/content if its filename differs.

The master matrix governs QDPI semantics.

The reset document governs this milestone.

Expected corpus:

* P1–P8 — *An author's preface*
* F1–F12 — *The Foreword to the Foreword to an author's preface*
* LF1–LF16 — *London Fox Who Vertically Disintegrates*
* PR1–PR5 — *Princhetta Who Thinks Herself Alive*

Expected total:

**41 authored pages**

and therefore:

**41 × 40 = 1,640 directed non-self pairs**

Verify this against the actual manifest.

Preserve authored prose and page boundaries exactly.

Reported existing capabilities include:

* Python local reader
* Jev/mock adapters
* corpus hashes
* experiment recording
* session history
* proposal / acceptance / Q / R mechanics
* operator criteria v0.1/v0.2
* two literary-review subagents

Verify those capabilities before rebuilding anything.

Preserve:

* existing work
* historical records
* reviewed mappings
* operator versions
* secrets
* corpus identities

Use the existing stack and conventions wherever reasonable.

The lead should briefly summarize what actually exists and what the team will add.

Then proceed.

---

# 3. THE PROBLEM

The current reader can offer individual operator selections, but it has not demonstrated:

1. a complete relationship map across the corpus, or
2. meaningful use of a reader's prior route.

The research target is the **story behind the story**:

> How does arriving at the same page through different previous passages change the possibilities for reading onward?

This milestone remains:

# Q → Q

Do NOT implement A or L generation.

Relationship assessments are evidence for possible Q bonds.

They are not automatically:

* established bonds
* generated pages
* human judgments
* reader preferences

`BRIDGE` remains an experimental relationship label.

It is not QDPI `L`.

Do not expand:

* Vault functionality
* mandatory reader notes
* evaluation forms
* broad application architecture
* unrelated cosmetics

---

# 4. FIX THE REPORTED INTERACTION PROBLEMS

Investigate using actual records and code:

### Case 1

Reported route:

PR1
→ DEVELOP
→ PR3
→ BRIDGE
→ PR2

Determine whether Discovery was active.

If Discovery's immediate-neighbor exclusion policy was active, PR3→PR2 should have been excluded.

Inspect:

* session policy
* candidate construction
* cache fingerprint
* result provenance
* eligibility filtering
* endpoint validation
* follow-time validation

Do not assign a cause until evidence supports it.

### Case 2

The reader displayed:

> Jev abstained (NONE) — no eligible destination

This conflates two different states.

Implement distinct states for:

* not requested
* loading
* selected
* abstained
* no candidates
* error

### Case 3

“Ask Jev again” reportedly flashed and caused the previous NONE result to disappear.

Reproduce this if possible.

Earlier outcomes must remain recoverable.

A rerun should create another persisted outcome rather than silently replacing historical evidence.

An abstention for one relationship type must not erase other available results.

Prevent:

* duplicate provider requests
* stale responses
* duplicate traversal
* unintended reader movement

Validate destination eligibility both:

1. when receiving a proposal
2. when following it

Keep manual navigation available.

---

# 5. AUDIT EXISTING DATA BEFORE MAKING NEW CALLS

The audit agent should classify existing records into at least:

* original 20-page experiments
* LF/PR 21-page experiments
* full 41-page experiments
* Discovery policy
* unrestricted policy
* criterion/rubric version
* page versions/hashes
* model
* mock/live

Do not infer coverage from request count.

Do not erase incompatible historical data.

Preserve it under its actual provenance.

Implement three clearly distinct layers:

## Layer 1 — Base pair profiles

Independent assessment of A→B.

## Layer 2 — Field-relative Choice distributions

Relative ranking when destinations compete inside a specified field/request.

## Layer 3 — History-conditioned judgments

Assessment of a transition given this particular reader history.

These are not interchangeable.

A Choice probability does not become an independent pair-quality score.

A base pair profile does not become a contextual judgment merely because it is reused during contextual selection.

---

# 6. IMPLEMENT THE COMPLETE BASE RELATIONSHIP ATLAS

For every ordered pair A→B, support seven separately assessed dimensions:

1. Direct Q fit
2. Echo
3. Development
4. Contradiction
5. Bridge relation
6. Redundancy
7. Missing context

Create concrete, versioned descriptive rubrics.

Each question should assess one dimension.

Do not collapse these into universal “interestingness.”

Relationships may legitimately be strong on several dimensions simultaneously.

Examples:

* strong Echo + strong Redundancy
* strong Development + moderate Missing Context
* strong Bridge + weak Direct Q Fit

Assess direction explicitly.

A→B and B→A are different entries.

Include immediate authored neighbors.

Discovery may filter neighbors at runtime, but the **base atlas must remain complete**.

For every assessment preserve sufficient provenance, including:

* source identity
* destination identity
* endpoint versions
* endpoint hashes
* supplied text/context
* rubric version
* model requested
* model returned
* raw provider answer
* distributions
* confidence
* usage
* timing
* validation result
* errors

Distinguish:

* unassessed
* failed
* stale
* assessed weak
* assessed valid

Missing does not mean zero.

Weak does not mean missing.

A pair counts as complete only when all seven required dimensions are valid under the active configuration.

Provide usable commands for:

* inspecting a pair
* checking atlas coverage
* building missing assessments
* resuming interrupted builds

---

# 7. VERIFY JEV BEFORE SCALING

Consult current official TypeSafe/Jev documentation, including:

* Quick start
* Score
* Choice
* API reference
* Models / limits / pricing
* official agent skill referenced from the quick start if applicable

Verify interfaces rather than relying on memory.

Use descriptive `Score` questions for independent dimensions where appropriate.

Batch independent questions only where supported and where endpoint identity remains unambiguous.

Do not assume one question inside a request can consume another question's answer.

Use the project's intentionally pinned model.

If only `jev-latest` is configured:

1. resolve the returned version during the pilot
2. record it
3. hold that returned version constant for the build if possible

Do not silently mix model versions.

Credentials already exist locally.

Use the existing secret/config loader.

Never print or copy credentials.

Never convert a failed live request into mock success.

---

# 8. RUN A SMALL LIVE DIAGNOSTIC BEFORE THE FULL BUILD

Use at minimum:

* F12→P8
* P8→F12
* PR1→PR4
* PR4→PR1
* LF1→LF3
* LF3→LF1
* two additional weak/ambiguous ordered comparisons selected from the actual corpus

Earlier interpretations are provisional calibration examples.

They are not human-approved ground truth.

Do not tune prompts until predetermined winners appear.

Reuse the project's existing literary reviewers if available.

For the diagnostic set:

* Reviewer 1 reads independently.
* Reviewer 2 reads independently.
* Neither reviewer sees Jev scores first.
* Neither reviewer sees the other's interpretation first.
* Their analysis should cite actual supplied prose.
* Their output remains interpretation, not ground truth.

Then compare:

* Jev dimensions
* reviewer interpretations
* actual text
* obvious failures of rubric separation

Correct concrete implementation/rubric problems.

Then freeze the assessment configuration before scaling.

---

# 9. LIVE WORK LIMITS

Across pilot + atlas build + contextual memory demonstrations:

* Maximum **2,000 new provider request attempts**
* Maximum **10 million estimated input tokens**
* Maximum **2 concurrent provider requests**
* Maximum **2 retries per request**
* Retries count toward the total
* Honor stricter existing user-configured limits

Account for SDK retries and in-flight requests.

Before large dispatch:

* measure pilot usage
* estimate remaining work
* estimate cost using current provider pricing
* record assumptions

Continue autonomously inside these limits.

Do not ask me to approve individual pairs.

Make the build:

* resumable
* checkpointed
* restart-safe
* compatible-result aware

Skip compatible successful entries.

If authentication/provider failures persist, stop boundedly rather than retrying the corpus indefinitely.

If limits prevent complete coverage:

* preserve exact completed coverage
* preserve exact failed coverage
* preserve remaining work
* finish the implementation
* provide the exact resume command

Never describe partial or mock coverage as a complete live atlas.

---

# 10. IMPLEMENT EXPLICIT READER MEMORY

Use existing session records.

Construct a versioned memory packet containing:

* current page/version
* ordered recent encounters
* traversal operations
* exact encountered prose
* active field
* candidate policy
* explicitly supplied reading intention, if any

Initial memory window:

**six most recent encounter events**

Preserve the complete session trace separately.

Clearly mark omitted history.

A database reference is not equivalent to text actually supplied to Jev.

Back navigation must not erase encounter history.

Returning to a page does not recreate the first encounter.

Do not infer:

* that visiting means liking
* that visiting means agreeing
* that visiting means endorsing an interpretation

Do not turn agent summaries into facts about the reader.

Contextual cache keys must include:

* actual memory packet
* memory policy version
* relevant endpoint versions
* relevant assessment/rubric/model configuration

Base pair data may be reused as base information.

It must never masquerade as a fresh contextual assessment.

---

# 11. CHART THE ROUTE-SELECTION PIPELINE EXPLICITLY

This is an important team task.

Before finalizing the implementation, have the atlas agent and memory agent independently trace the runtime path from active page to offered route.

The intended initial pipeline is:

current page
→ retrieve 40 base profiles
→ deterministic eligibility/filter policy
→ deterministic bounded shortlist
→ construct actual reader memory packet
→ contextual assessment of shortlist
→ qualification/ranking policy
→ up to three route offers
→ reader preview/follow
→ proposal record
→ acceptance record
→ Q traversal record
→ updated reader state

Record why every shortlisted candidate entered the shortlist.

Do not hide selection inside a single opaque model call.

Do not claim all 40 candidates received history-conditioned assessment if only the shortlist did.

---

# 12. OFFER SEVERAL ROUTES

Implement a small inspectable selection policy.

Use base profiles to construct a bounded shortlist.

Initial shortlist construction should be deterministic and versioned.

Record:

* candidate
* relevant base dimensions
* reason included
* reason excluded where useful

Then assess shortlisted destinations against the actual memory packet.

Contextual judgment should keep separate questions such as:

* Does this transition work after this particular history?
* Does it add a supported reading effect?
* Does it excessively repeat what this reader has just encountered?

Do not collapse these into “interestingness.”

Offer up to:

**three qualified destinations**

Do not force three.

Do not force:

* a contradiction
* a cross-text move
* a revisit
* a non-neighbor
* any particular operator label

Do not relabel weak evidence merely to populate a card.

Ordinary navigation must remain available.

Revisiting may become meaningful after intervening history.

Do not universally ban it.

Keep optional randomness out of the first implementation unless it materially helps.

If randomness is used:

* sample only from qualified candidates
* record the eligible pool
* record the seed

---

# 13. PR2 MEMORY DEMONSTRATION

Create isolated comparison fixtures for PR2.

These are demonstrations.

They are not fabricated user history or automatically accepted bonds.

Compare:

### Condition A

PR1 → PR3 → PR2

### Condition B

LF3 → PR2

### Condition C

PR2 with no previous supplied reading history

Hold constant:

* PR2 version
* candidate shortlist
* candidate order
* model
* rubrics
* provider configuration
* ranking/offer policy

Change only declared arrival history.

Show:

* exact supplied history
* actual provider inputs/provenance
* contextual assessments
* several resulting route possibilities

Do not require a winner flip.

The code is correct if history genuinely reaches the decision process and the comparison is reproducible.

Then separately evaluate whether resulting judgment differences appear textually meaningful.

Keep:

**software correctness**

separate from:

**evidence of literary usefulness**

If the literary effect is weak, say exactly what is weak.

Do not begin endless automatic prompt tuning.

---

# 14. INTEGRATE THE ATLAS + MEMORY LOOP INTO THE READER

The reader experience should become:

1. Read a page.
2. Receive a small hand of supported next-page possibilities.
3. Preview one.
4. Follow one.
5. Continue reading with history automatically recorded.

On an explicit request/offer action, a cache miss may trigger necessary bounded assessment.

Browser refreshes must not trigger uncontrolled provider work.

Duplicate clicks must not create uncontrolled provider work.

Cards should show:

* destination identity
* useful supported relationship labels
* readable destination/source preview

Put deeper technical information behind optional expansion:

* scores
* confidence
* provenance
* memory details
* model
* usage
* exact contextual reasoning data where appropriate

Use recorded authored text exactly.

Do not fabricate literary prose and attribute it to Jev.

Existing agent commentary may be shown when available, but clearly label:

* authoring agent
* provenance
* status as interpretation

The reader must work without requiring a second provider.

Keep these events distinct:

* proposal
* acceptance
* Q traversal

Following a route does not create a human literary-quality judgment.

Preservation remains its existing explicit action.

Do not automatically save exploration into the Vault.

Add a lightweight way to inspect the active page's **40 base pair profiles** and their coverage.

A readable list/table is enough.

Do not build a giant graph visualization unless the existing architecture makes one essentially free.

---

# 15. TEST THE RISKS THAT ACTUALLY MATTER

Add focused tests covering:

* 41 corpus identities
* 1,640 ordered non-self pairs
* inclusion of adjacent pairs
* directionality
* complete vs weak vs missing vs failed
* version invalidation
* hash invalidation
* resumable atlas jobs
* reuse of compatible results
* request limits
* token limits
* retry accounting
* mock/live separation
* Discovery filtering
* unrestricted policy behavior
* cache compatibility
* abstention rendering
* rerun behavior
* persistent historical outcomes
* error state
* stale response rejection
* duplicate request protection
* duplicate traversal protection
* memory-sensitive cache keys
* exact memory assembly
* back navigation preserving encounters
* proposal leaving reader position unchanged
* acceptance/traversal distinction
* follow-time eligibility validation

Run relevant existing checks.

Run an offline end-to-end path.

Exercise the reported rerun bug using available browser/integration capabilities.

State verification limitations honestly.

---

# 16. ADVERSARIAL TEAM REVIEW BEFORE INTEGRATION

Before declaring completion, have the independent reviewer inspect the integrated work.

The reviewer should attempt to falsify the following claims:

### Claim A

The atlas is complete.

Check actual valid dimensions across all 1,640 pairs.

### Claim B

History changes provider context.

Inspect actual provider packets/cache keys.

### Claim C

History-conditioned results are not confused with base profiles.

Inspect storage and runtime code.

### Claim D

Discovery is only a runtime policy and does not leave holes in the atlas.

Inspect adjacent-pair coverage.

### Claim E

Weak relationships remain weak instead of being coerced into offers.

Inspect qualification logic.

### Claim F

NONE / no candidates / error are truly different states.

Inspect runtime and persistence.

### Claim G

The reader does not move until a route is actually followed.

Inspect proposal/acceptance/traversal state transitions.

### Claim H

Mock data cannot masquerade as live Jev coverage.

Inspect provenance and reporting.

### Claim I

Reader history is descriptive, not psychological inference.

Inspect memory construction and prompts.

### Claim J

No A/L generation has accidentally entered this Q→Q milestone.

Inspect runtime and semantics.

The lead should resolve confirmed problems before final handoff.

Do not “fix” reviewer objections merely by changing documentation when the underlying implementation is wrong.

---

# 17. UPDATE PROJECT DOCUMENTATION

Update README commands so they actually work.

Create a concise implementation-status document for future Claude Code sessions containing:

* what changed
* active schema versions
* active rubric versions
* active model/version
* coverage
* provider usage
* unresolved failures
* current reader commands
* demo commands
* resume commands
* verification performed
* known limitations

A future agent should be able to recover the state without access to this conversation.

---

# 18. RESTART THE READER SAFELY

Restart the existing localhost reader if needed.

Do not disturb unrelated processes.

Preserve the real reader session.

Make demonstration fixtures separately accessible.

---

# 19. FINAL HANDOFF

Return a short human-readable handoff.

Do not dump giant JSON structures or side-by-side terminal tables.

Include:

1. **What I can now do that I could not do before.**

2. **Actual live atlas coverage.**

   * complete pairs / 1,640
   * failed
   * stale
   * remaining

3. **Actual live provider work.**

   * request attempts
   * input/output usage where available
   * estimated cost
   * model/version

4. **Where to open:**

   * normal reader
   * atlas inspection
   * PR2 memory comparison

5. **Three simple steps for trying the new experience.**

6. **Any remaining blocker and its exact next action.**

7. **Agent-team summary.**
   Briefly state:

   * which agents investigated which pathways
   * which implementations were integrated
   * any disagreement between agents that materially changed the final design

Keep detailed records in repository files.

---

# THE FINISH LINE

Do not optimize for “many changes.”

Optimize for this working loop:

> From any of the 41 original authored pages, I can inspect the complete base relationship data, arrive at that page through a recorded reading history, receive a small set of traceable next-page possibilities informed by that history, preview them, and follow one without filling out a form.

The system should preserve uncertainty.

It should preserve weak relationships.

It should preserve history.

It should preserve provenance.

It should preserve distinctions between:

* page relationships
* field-relative rankings
* reader-conditioned judgments
* agent interpretations
* human choices

The purpose is not to prove that there is one correct path through Gibsey.

The purpose is to build enough explicit relational structure and reader memory that **different paths through the same authored field can become computationally inspectable and meaningfully responsive to how the reader got there.**

Use the team to chart those pathways before collapsing them into implementation.