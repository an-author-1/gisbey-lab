# Gibsey Lab

A working laboratory for **QDPI and Field Intelligence**, learning AI engineering and inference engineering through small, inspectable Gibsey experiments.

**Central question: What becomes adjacent to a passage, under which circumstances, and with what effect?**

Gibsey supplies the authored world and literary material. The lab investigates context assembly, literary connections, reader state, evaluation, and inference performance for future Gibsey demos and the broader Holographic system.

**Jev is a core component of the first experiments.** We will use it to make structured judgments about supplied passages and candidate connections, then inspect those judgments against the text. Language models can supply written interpretations and, in later experiments, generate material under the appropriate QDPI function.

**Status — 19 September 2026:** This README is the launch plan. The initial commit will contain this document, the QDPI master function matrix, and the twenty authored Pages. The experiment harness, integrations, and results still need to be built. Everything below marked as a proposed path, experiment, or component describes intended work, not an existing feature.

---

## Repository Setup

1. Put this file at the root of `gibsey-lab` as `README.md`.
2. Add the supplied matrix as `QDPI-master-function-matrix.md`. The revision dated **18 September 2026** is the current protocol reference.
3. Create an Obsidian vault in `vault/`, with the two folders below. Use one Markdown file per authored Page.
4. Preserve the exact wording and Page boundaries. Give files stable IDs: `P1.md`–`P8.md` and `F1.md`–`F12.md`.
5. Add the existing F12 sentence mapping, if available, as a separate reference. Preserve its nine units, `F12.S1`–`F12.S9`; do not silently regenerate them.
6. Commit and push this source material. The next build step is a small local experiment harness that reads these files and connects to Jev.

| Corpus folder                                                | Material                                            | Page IDs   | Count |
| ------------------------------------------------------------ | --------------------------------------------------- | ---------- | ----: |
| `vault/an author's preface/`                                 | an author's preface                                 | `P1`–`P8`  |     8 |
| `vault/The Foreword to the Foreword to an author's preface/` | The Foreword to the Foreword to an author's preface | `F1`–`F12` |    12 |

These are proposed folder names. If the committed folders differ, the loader should map their actual paths to the same stable Page IDs without rewriting the authored text. Keep sentence annotations and generated metadata outside the source prose.

**The Obsidian vault is the source workspace. The Gibsey Vault is a QDPI concept:** a reader's explicitly preserved selections and versions. Putting a source Page in Obsidian does not automatically perform R or adopt it into a reader's canon.

---

## What Jev Contributes

[TypeSafe's documentation](https://docs.typesafe.ai/introduction) describes Jev as a model that evaluates supplied state through typed questions. Its documented primitives give the lab three starting tools:

| Primitive                                            | Documented output                                                        | Proposed Gibsey experiment                                                                        |
| ---------------------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| [Choice](https://docs.typesafe.ai/primitives/choice) | A selected option, option probabilities, and confidence                  | Select a candidate destination from explicit IDs, including an abstention option.                 |
| [Score](https://docs.typesafe.ai/primitives/score)   | A position on defined, ordered levels, with probabilities and confidence | Evaluate one aspect of a candidate connection against a small literary rubric.                    |
| [Noul](https://docs.typesafe.ai/primitives/noul)     | The probability of a yes/no judgment; no separate confidence field       | Ask a focused question such as whether a passage reverses the active passage's account of agency. |

These applications are **lab hypotheses to test**. Jev receives the passage text and relevant state; it is not assumed to know Gibsey, remember previous runs, or retrieve missing Pages. The lab supplies that material and records the result.

Questions submitted together are evaluated independently against shared state. If one decision must depend on another answer, combine the results in code or make a subsequent call. Put each question's subject in its instructions, rather than relying on its record key. See the [introduction](https://docs.typesafe.ai/introduction) and [Choice request structure](https://docs.typesafe.ai/primitives/choice).

[TypeSafe confidence](https://docs.typesafe.ai/confidence) summarizes the shape of an answer's probability distribution. In this lab, confidence, predicted literary quality, and human judgment are separate records. A confident selection can still be unhelpful; several compelling candidates can produce uncertainty. Thresholds must be evaluated on Gibsey cases before they control behavior.

The [official quick start](https://docs.typesafe.ai/introduction/quickstart) covers the Playground, API, SDKs, and a TypeSafe skill for Claude Code. The build should consult those current interfaces, record the model identifier and dependency versions used, and keep credentials out of commits and run logs. If only a moving model alias is available, record it and the run date without claiming the model weights are pinned.

If Jev access is pending, corpus validation and a clearly labeled mock adapter can still be built. Mock results never count as Jev evidence; completing the first Jev milestone requires a real recorded call.

---

## Responsibilities

| Component                  | Responsibility                                                                                                           |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Authored corpus and matrix | Supply the exact literary material and current QDPI definitions.                                                         |
| Application code           | Load versions, enforce eligibility and access, assemble context, validate results, and apply explicit state transitions. |
| Jev                        | Make bounded choices and judgments using supplied state and defined answer spaces.                                       |
| Language model             | Supply an optional written interpretation, a comparison baseline, or later QDPI generation.                              |
| Human reader/researcher    | Judge literary effects, accept or reject proposals, and choose what to follow or preserve.                               |

Persistent state belongs to the application. Editing prompts, rubrics, examples, or routing rules changes the experiment; it does not by itself fine-tune Jev or another model's trained weights.

---

## QDPI: The Governing Distinctions

Use [the master function matrix](QDPI-master-function-matrix.md) for complete input, authorship, routing, and preservation rules. This table is a summary; the matrix governs when shorthand leaves something unclear.

| Function                | Meaning relevant to the lab                                                                                                                                          |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Q — Queue**           | Follow an existing one-to-one bond to an accessible Page/version. Traversal requires no text generation.                                                             |
| **A — Altologue**       | The native character agent creates a linked variation of an eligible source version. Preserve the source and alteration history.                                     |
| **R — Rememologue**     | Human writing, or explicit indexing: saving, submission, or acceptance of selected material. Preserve its actual authorship and chosen version.                      |
| **M — Monologue**       | Activate an agent-authored expansion bond anchored to a particular Page. Selecting it does not change the bond's authorship.                                         |
| **D — Dialogue**        | Address a Page-connected question to an identified participant. Preserve the question, actual respondent, and linked answer; human answers use R's writing function. |
| **L — Link / Hololink** | Generate a connecting Page or ordered sequence between specified endpoint versions.                                                                                  |
| **H — Holologue**       | A character agent produces one non-episodic synthesis Page from a selected contextual field.                                                                         |
| **X — Xolologue**       | A character agent produces a structured episode, story, or section comprising Pages.                                                                                 |

**Finding a possible bond and following it are separate events.** A Jev selection is a proposal for a connection. After validation and deliberate acceptance, an existing bond can be followed through Q. Discovery is an implementation step, not a ninth QDPI function or a redefinition of Q.

An optional model explanation in a run log is research commentary. It becomes a Gibsey Page only through an explicitly defined operation with the necessary context and authorship. A model's being the author does not automatically make an output M.

Creation follows the active working index: AGI, ASI, ACI, or AFI. Using another index's material as context does not move the result there; cross-index submission is an R action. Preserve the matrix's provisional status for the H/X routing extension. The first harness models a private AGI working context and explicit Vault saving; shared/public participation can be designed later.

---

## Working Principles

* Begin with twenty Pages and a few well-described cases.
* Preserve source IDs, exact versions, selected connections, and authorship.
* Keep authored text, model proposals, accepted bonds, and saved selections distinguishable.
* Treat similarity as one signal. Ask what the correspondence does to the reading.
* Include the active passage and its containing Page when the condition calls for both.
* Enforce exact rules in code: IDs, access, eligibility, quotation matches, and state transitions.
* Allow several successful literary answers. Earlier human choices are references, not the only permissible destinations.
* Change one experimental variable at a time, with inputs and results retained for comparison.

---

## The First Field and Interaction

The source Field contains the eight Preface Pages and twelve Foreword Pages listed above. This README reproduces only the previously identified active sentence:

> **F12.S4:** “You are both the Imaginator constructing the rides as you ride them, as well as the park goer who rides them.”

Verify that sentence and its nine-sentence mapping against the supplied authored F12 before running the micro experiment. If the mapping is missing, establish and review it explicitly. Record a corpus version or Git commit with every run. Later changes to boundaries require a new mapping while the original remains recoverable.

Earlier macro connections, `F12 → F3` and `F9 → F7`, can become reference cases once their full passages and rationales are available. Keep those judgments out of test input unless deliberately testing examples.

The organizing function remains:

```text
assemble(event, state, field) -> context_packet
```

| Component      | Contents                                                                                                          |
| -------------- | ----------------------------------------------------------------------------------------------------------------- |
| Event          | The reader's explicit action: select a passage, request a proposal, follow a bond, or save a selection.           |
| State          | Active Page/passage, working index, traversal history, participants, available operations, and access scope.      |
| Field          | Versioned source material and existing relationships available to the application.                                |
| Context packet | Task instructions, exact source text, eligible candidate evidence, and relevant state supplied for this decision. |

For discovery, code identifies eligible candidates, assembles the packet, calls Jev, validates the answer, and records a proposal. The active reading location remains unchanged until the reader follows an accepted bond. Existing bonds can be followed directly without another model call.

---

## Experiment 01 — Jev Selects One Grounded Micro Connection

**Question:** Can Jev select a meaningful nonadjacent sentence to place beside `F12.S4`?

**Input:** F12's exact nine labeled sentences in their original order, the active ID `F12.S4`, and one Choice question.

**Options:** `F12.S1`, `F12.S2`, `F12.S6`, `F12.S7`, `F12.S8`, `F12.S9`, and `NONE`.

Exclude the active sentence and its immediate neighbors, `F12.S3` and `F12.S5`. This is a same-Page micro experiment; macro cases use other Pages.

Use this working instruction for the Choice question:

```text
The active passage is F12.S4. Choose the eligible sentence whose
juxtaposition most clearly changes, sharpens, or complicates our reading
of it through a specific correspondence grounded in the supplied text.
Shared topic alone is insufficient. Choose NONE if no eligible sentence
supports a defensible correspondence. Use only the supplied F12 text.
```

The adapter supplies the explicit options and their corresponding text references using the current Choice schema. This instruction is a proposed experimental prompt, not a complete API request.

Save the full request, raw response, option distribution, confidence, model identifier, timing, and any reported usage. Map `NONE` to an abstention in the lab record, keeping the original response intact. Resolve selected IDs to their exact source text in code; Jev does not need to generate quotations or a prose rationale.

Read the selected pair and write a short human review:

**What is the correspondence? What does it do? Why does it matter?**

An optional language-model explanation must be separately attributed and assessed; it is not Jev's reasoning or independent proof of the selection's quality.

Repeat the unchanged request twice more when practical. Three trials show initial variability, not statistical reliability. A language-model selection baseline can use the same text, criterion, and allowed choices, with its own interface and settings recorded.

**Done when:** One real Jev decision or abstention has a complete record, exact validity checks, a human literary review, and a concrete next question.

---

## Experiment 02 — Context and Decomposed Judgments

**First question:** What changes when the containing Page and reader history are included?

Hold the candidate evidence, order, Choice question, model, and exposed settings fixed.

| Condition | Source context                                                   | Candidate evidence                                          |
| --------- | ---------------------------------------------------------------- | ----------------------------------------------------------- |
| A         | Active sentence only                                             | Fixed packet containing every compared target's ID and text |
| B         | Active sentence plus containing Page                             | Same packet                                                 |
| C         | Active sentence, containing Page, and relevant traversal history | Same packet                                                 |

For F12, the candidate packet already exposes much of the Page. Adding F12 also supplies the excluded neighbors and original ordering; record this overlap. A macro case offers a clearer test of containing-Page context. History must be an actual recorded traversal or a labeled hypothetical fixture.

**Subsequent question:** Does separating judgments help explain or improve candidate selection?

With context held fixed, try separate Score questions for each candidate's textual correspondence and effect on the active passage. Define the levels before running them, using the human evaluation rubric below as a starting point.

A Noul question can test a specific relation, such as a reversal of agency, when that relation matters to the case.

These remain predictions to evaluate. If code combines scores, record the formula, weights, and abstention rule. A Choice in the same request does not consume those Score answers; testing score-informed selection requires a later step. Do not change the context and scoring method in the same comparison.

**Done when:** One controlled comparison identifies a contribution of context or decomposition—or a failure to demonstrate one.

---

## Experiment 03 — Macro Assembly and Retrieval

**Question:** Can the lab find a useful correspondence elsewhere in the twenty-Page Field?

Start from a Page such as F12 and exclude it as its own destination. Set any additional rule before running the case; exclude sequential neighbors only when the case requires a nonadjacent jump.

First give Jev the full eligible Field and ask for a destination or `NONE`. Compare this with a deliberately assembled subset under the same criterion. Log which candidates each condition exposes. A condition with no destination evidence should abstain, and should be reported separately.

As the experiment develops, compare candidate sources:

| Method                           | Question to inspect                                                         |
| -------------------------------- | --------------------------------------------------------------------------- |
| Full eligible Field              | What happens when all nineteen other Pages are available?                   |
| Human selection                  | Which candidates appear useful to a reader, and why?                        |
| Keyword search / BM25            | Which lexical correspondences are found or missed?                          |
| Embedding similarity             | Which semantic neighbors are found, and which useful differences disappear? |
| Existing bonds / graph traversal | What do recorded relationships make available?                              |
| Jev scoring and selection        | How well does it judge the candidates actually supplied?                    |

Apply access and eligibility rules before sending material. Jev's selection from a candidate packet does not establish that the retrieval process found every useful passage.

Evaluate candidate discovery, context inclusion, and final selection separately. Twenty Pages are enough to begin without a vector database.

**Done when:** A recorded comparison shows where a useful connection was found, missed, or weakened.

---

## Experiment 04 — Reader State, Q, and R

**Question:** Can the same recorded decisions produce predictable reader state?

| Action                                       | Expected effect                                                                              |
| -------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Open F12                                     | Set the active Page and record the visit.                                                    |
| Select F12.S4                                | Set the active passage; retain F12 as its containing Page.                                   |
| Request and inspect a Jev proposal           | Store the result and review without moving the reader.                                       |
| Accept and follow a validated bond through Q | Record acceptance, then traverse to the exact target version and append the traversal event. |
| Preserve the selected realization through R  | Save its version, provenance, and selected connections to the reader's Vault.                |

Record state before and after each action.

Invalid outputs, abstentions, and failed calls leave the location unchanged. Replaying the same save event must not create an unintended duplicate. Replay uses saved outputs rather than asking a model to reproduce its earlier judgment.

**Done when:** The event record reconstructs the resulting state, and the saved realization remains identifiable after later experiments.

---

## Evaluation From the Beginning

| Check                                                       | Method                                                                                                  |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Destination exists and is eligible                          | Pass/fail against the versioned Field and case rules                                                    |
| Copied or generated quotations match their cited units      | Exact substring check                                                                                   |
| Response has expected types and options                     | Schema validation and allowed-ID checks                                                                 |
| State changes obey the matrix and access rules              | Deterministic application checks                                                                        |
| Correspondence is specific and grounded                     | Human score: 0 absent, 1 plausible but thin, 2 convincing                                               |
| Juxtaposition changes or sharpens the reading               | Human score: 0 absent, 1 limited, 2 substantial                                                         |
| Interpretation uses the active passage and relevant context | Human score: 0 ignores them, 1 partial, 2 well supported; apply only when an interpretation is produced |

Keep validity, model scores, confidence, and literary quality separate.

Review abstentions against the evidence available. Do not use Jev as the sole judge of its own outputs. Record more than one worthwhile destination when appropriate, and preserve disagreements rather than flattening them into one answer key.

Build a small case collection and hold some cases out of prompt development. Review new plausible candidates and version relevance judgments; an initial reference list is not exhaustive. Repeated comparisons and held-out review should precede claims about improvement or confidence calibration.

For a disappointing run, locate the earliest observed failure:

**missing source material → missed retrieval → poor context assembly → weak judgment → incorrect application action**

---

## What to Save for Each Run

Use one directory per run. Markdown is enough for initial human notes; automation should also preserve machine-readable requests, responses, and events.

| Record       | Required information                                                                                            |
| ------------ | --------------------------------------------------------------------------------------------------------------- |
| Identity     | Run ID, timestamp, case, condition, trial, hypothesis, live/mock status                                         |
| Versions     | Corpus commit or content hashes, matrix revision, sentence mapping, assembler, question/rubric version          |
| Context      | Active Page/passage, working index, participants, history, access scope, eligibility rules                      |
| Candidates   | IDs found, IDs supplied, exact text versions, order, and any filtering                                          |
| Request      | Complete supplied state, questions, option descriptions, model and exposed settings; omit credentials           |
| Response     | Unedited provider result, probabilities/confidence where returned, normalized selection or abstention           |
| Review       | Validity results, human scores and reasons, optional separately attributed interpretation, acceptance/rejection |
| Events       | Explicit actions, state before/after, selected versions and saved bonds                                         |
| Measurements | Elapsed time, reported usage, retries/errors, cost and pricing date if known                                    |
| Finding      | What worked, what failed or remains uncertain, and the next single variable to change                           |

Record unavailable measurements as unknown.

Measure Jev decisions, language-model commentary, and total interaction time separately. Count every call in a multi-step workflow. Observable outputs and explanations do not reveal a model's internal reasoning.

---

## Foundation to Build Next

The first implementation should be a small local harness:

* corpus loader
* reviewed sentence mapping
* context assembler
* Jev adapter
* proposal validator
* run recorder
* minimal reader-state handling

Keep model integration separate from QDPI rules so experiments can compare providers without changing the protocol.

| Proposed path                    | Purpose                                                                     |
| -------------------------------- | --------------------------------------------------------------------------- |
| `README.md`                      | Lab purpose and experiment plan                                             |
| `QDPI-master-function-matrix.md` | Current QDPI reference                                                      |
| `vault/`                         | The two folders containing exact authored Markdown Pages                    |
| `data/`                          | Corpus manifest, versioned sentence mappings, and derived data              |
| `cases/`                         | Inputs, eligibility, histories, and review criteria                         |
| `prompts/`                       | Versioned Jev questions/rubrics and optional language-model prompts         |
| `src/`                           | Loader, assembler, adapters, validation, records, and state handling        |
| `runs/`                          | Requests, responses, measurements, reviews, and event records               |
| `notes/`                         | Findings and open questions                                                 |
| `tests/`                         | Meaningful checks for corpus integrity, eligibility, and state preservation |

There is no project installation or run command yet. The next build should add the actual commands and update this status after verification.

Keep API secrets and transient Obsidian workspace settings out of Git; add a credentials template containing names only.

### First Milestone Acceptance Checklist

* [ ] The corpus loads all twenty Pages with stable IDs and preserved text.
* [ ] F12's nine-sentence mapping is available and reviewed.
* [ ] Experiment 01 has an explicit candidate set, abstention option, and success criterion.
* [ ] A real Jev call is recorded with its exact input, output, and versions.
* [ ] Code validates the selected destination; a human reviews its literary effect.
* [ ] An accepted bond can be followed through Q with an explicit recorded transition.
* [ ] R preserves the selected realization and connections without overwriting the source.
* [ ] The run produces evidence and a specific next question.

---

## Learning and Later Experiments

The central skills remain **context assembly, protocol/state design, and evaluation**.

Learn model calls, JSON, file handling, error handling, and Git through those experiments.

After the first milestone, compare:

* context budgets
* repeated decisions
* candidate ordering
* request batching
* result caching
* additional calls

Compare them against observed quality, elapsed time, and cost.

For generative models, also study streaming, output budgets, prompt caching, prefill, and decode. Record only exposed measurements; total request time does not isolate provider internals.

Any result-cache key must reflect all decision-relevant inputs, including:

* source and candidate versions
* active passage
* state
* access
* instructions
* model
* settings

A Page ID alone is insufficient.

Later experiments can test Jev's recognition of QDPI operation intent, using complete event context and the matrix as the reference. Actual authorship, permissions, and index destinations must remain explicit application records.

Define each generation operation and its evaluation before implementing it. Shared indexes, autonomous agents, fine-tuning, and self-hosted inference belong to later questions with concrete experimental reasons.

---

**The first goal is a small, repeatable interaction whose choices we can inspect—and whose effect on reading is worth returning to.**
