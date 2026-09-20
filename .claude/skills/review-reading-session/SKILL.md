---
name: review-reading-session
description: Review the most recent Gibsey Lab reading-session traversals using two independent, read-only agent perspectives (close reading and skeptical reading). Saves findings separately from human review notes and returns a short digest.
when_to_use: The user asks to review their latest reading session, review recent Gibsey Lab traversals, or get an agent perspective on connections they just followed in the reader.
allowed-tools: Read, Bash, Agent, Write
---

## What this does

Reviews at most the 10 most recent Q traversals (accept-and-follow events) recorded by
the local Gibsey Lab reader, using exactly two bounded agent tasks -- a `close-reader` and
a `skeptical-reader` -- that never see each other's output or Jev's confidence, and never
change anything about the reading session. The reader app does not need to be running;
this only reads `data/session_log.jsonl` and existing run directories under `runs/`.

## Steps

1. From the `gisbey-lab` project root, run:

   ```
   .venv/bin/gibsey session-review-data --limit 10
   ```

   This prints a JSON list of up to 10 traversals, each with the exact recorded source
   text, destination text, operator, and criterion (no confidence/probabilities -- they
   are deliberately not included). If it prints `[]`, tell the user there is nothing to
   review yet and stop here. Do not invent traversals.

2. Build one bundle containing all the gathered traversals. Send this identical bundle,
   in a single message with two parallel Agent tool calls, to:
   - `subagent_type: "close-reader"`
   - `subagent_type: "skeptical-reader"`

   Do this in one message so neither call depends on or can see the other's result.
   Do not tell either agent Jev's confidence or otherwise hint at how strongly the
   original selection scored -- that information is intentionally withheld from them.

3. Once both agents return, write a findings file to
   `data/agent_reviews/<UTC timestamp of this run>.md` (create the `agent_reviews/`
   directory if needed) containing:
   - The list of traversals reviewed (source id, operator, destination id, run_dir,
     timestamp).
   - A `## Close reader interpretation (agent, not Jev, not a human reviewer)` section
     with that agent's full output.
   - A `## Skeptical reader interpretation (agent, not Jev, not a human reviewer)`
     section with that agent's full output.

   This file is separate from any run's `review.json`/`review.md` (human-only) and from
   `data/session_log.jsonl` (a passive navigation record, not a review).

4. Reply to the user with a short digest only:
   - Up to three interesting connections, drawing on both agents' findings, each citing
     the specific traversal (source -> destination, operator) it refers to.
   - Any concern either agent raised with clear textual support -- state it plainly, do
     not soften or oversell it.
   - The path to the saved findings file, for anyone who wants the full text.

   Do not print the full agent outputs directly into the chat -- the file is where the
   full text lives; the reply is a digest.

## Explicit limits

Do not, as part of this skill:

- Change ECHO/DEVELOP/CONTRADICT/BRIDGE wording or any other operator definition.
- Call any accept/follow action (`/api/accept`, `/api/accept-and-follow`,
  `state.accept`, `state.follow`) or otherwise move the reader's position.
- Write to any run's `review.json` -- that field is for the human reader only.
- Turn the agents' commentary into a new Gibsey Page, Vault entry, or any other
  in-world content.
- Make any new Jev call. This skill only reads what the reader has already recorded.
