# Session 3 browser demonstration

The final successful run is [`20260926T012138680016Z/report.json`](20260926T012138680016Z/report.json).
It used installed Chrome through Playwright, a new browser context, a dynamically allocated
localhost port and the retained `isolated-store/` beneath that run. Brennan's live stores
and reader port were not used. The report records actual build revision `6e7221c` with
uncommitted implementation changes and the served JavaScript hash. Times in filenames
are UTC (September 26); this was September 25 in America/Chicago.

Run again from the repository root:

```sh
.venv/bin/python tests/acceptance/run_score_demo.py
```

The sandbox required approval for the local socket and Chrome. Each run creates its
own timestamped directory and stops its server afterward. The server harness disables
live providers. Both contextual and single-pick dispatch counters were zero before
and after a real server process restart; there were no JavaScript page errors.

## Browser observations

- Literary neutral Q and a page-list relocation remain in one continuous journey.
- On synthetic RX3, neutral offers RX1, RX5 and RX7; recurrence offers RX5 and RX7
  and explains that RX1 was already visited. The reader shows outward progress 1 of 2.
- Previous, Next, in-app Back, page list and browser Back cannot relocate the active
  recurrence performance. A direct URL reload resumes RX3 without a new arrival.
- Pause/resume preserves encounters and movement progress. Server restart and reload
  preserve exact passage text, identity, score configuration, movement and counters.
- A stale second tab cannot commit its old RX3 offer after another tab reaches RX5.
- RX1 is the only return choice at RX5. Following it completes the performance.
  The journey inspector displays deciding rules, prior encounter references and spacing:
  candidate arrival index 3, index distance 3, two intervening encounters.
- An unavailable operator shows a blocked outcome. Selecting a valid operator can
  recover availability without moving or changing the rules. Reader ending and leaving
  are explicit; Leave restores the prior literary journey and retains a demo inspect link.

Screenshots in the final run: `neutral-early-return.png`,
`recurrence-early-return-excluded.png`, `recurrence-return-available.png`,
`recurrence-complete.png`, `recurrence-blocked.png`, `journey-rule-inspection.png`.

## API and replay evidence

The same browser context also made explicit API probes; these are recorded separately
in the report. Seven legacy research POST routes and two legacy GET routes return 409
during recurrence. A pre-pause offer remains invalid after resume. An identical accepted
action retry returns the original result; conflicting request-ID reuse is rejected.
None adds an arrival or advances a counter.

All four new journey exports under the final run's `bundles/` pass provider-disabled
state replay, decision replay and retained-content/score-snapshot checks: literary
neutral, synthetic neutral, recurrence completion, and blocked/reader-ended recurrence.
The full recurrence inspection response is `recurrence-journey.json`; the isolated
journals and exact retained inputs remain available in the same run.

Focused test command:

```sh
.venv/bin/python -m pytest tests/test_reader_core.py tests/test_reader_core_scores.py tests/test_reader_interaction.py -q
```

Result: **113 passed**. Tests cover all declared manual causes including browser
Forward, unavailable legacy routes before mutation, availability without revision
advancement, and exact text first retained after session start. Browser Forward itself
was not separately exercised in this focused browser run; its server policy is covered
by the parameterized reader test. Firefox/Safari and keyboard-only operation were not run.

## Brennan's clicks

1. Open the reader serving this working tree. Click **Try neutral choices**, then
   **Follow** RX3. Click **ECHO**: RX1 is available immediately.
2. Click **Leave demonstration**, then **Try outward and return**. Follow RX3 and
   click **ECHO**: RX1 is excluded with an explanation. Previous/Next cannot bypass it.
3. Follow RX5 and click **ECHO**: RX1 is now available. Follow RX1: the performance
   reads **Complete**. The journey link shows the rules and earlier encounters.
4. Click **Leave demonstration** to restore the literary journey. The demo remains
   inspectable through the link shown after leaving.

Earlier outputs are retained transparently: `20260926T011752463289Z` records the first
run's blocked-label display failure, fixed in the reader; `20260926T011824835788Z` is
an intermediate passing run before final wording, legacy GET checks and retained-text
coverage. `20260926T012030385481Z` also passes; its inspector screenshot precedes the
final framing centered on the return-spacing rule. The empty `20260926T011738500075Z` directory came from the initial sandbox
socket denial. Use the final successful run for the current evidence.
