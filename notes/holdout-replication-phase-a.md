# Holdout replication, Phase A: forward field

Uses the two new stories added to the vault — **London Fox Who Vertically Disintegrates**
(LF1-LF16) and **Princhetta Who Thinks Herself Alive** (PR1-PR5) — 21 pages total, none of
which played any role in designing, refining, or observing Q Operator Prototype v0.1
(frozen in `notes/q-operator-prototype-v0.1.md`). Operator wording is exactly the frozen
v0.1 text, unchanged. Model pinned to `jev-1.13.0` (84/84 confirmed).

**Size note:** the plan specified a 20-page field (80 calls); the actual holdout corpus
delivered is 21 pages (16 + 5), so this is **84 calls**, not 80. Run in full rather than
dropping a page to force the original count. Loaded via a standalone script-local loader,
entirely separate from `gibsey_lab.corpus` (which only scans the original two training
folders) — no code path could mix the two corpora.

Full edge list: `runs/relop-holdout-full-field-edges.csv`. Per-run records:
`runs/*_relop-holdout-full-<source>-<operator>_live/`.

All 84 calls succeeded. 0 NONE selections.

## Edge matrix

| Source | Echo | Develop | Contradict | Bridge |
| --- | --- | --- | --- | --- |
| LF1 | LF6 (0.60) | LF6 (0.28) | LF3 (0.33) | PR1 (0.09) |
| LF2 | LF1 (0.20) | LF11 (0.36) | LF3 (0.22) | LF11 (0.11) |
| LF3 | LF4 (0.67) | LF6 (0.39) | LF10 (0.27) | PR1 (0.18) |
| LF4 | LF3 (0.69) | LF3 (0.54) | LF3 (0.18) | LF3 (0.19) |
| LF5 | LF3 (0.56) | LF6 (0.35) | LF6 (0.18) | PR1 (0.16) |
| LF6 | LF9 (0.32) | LF7 (0.27) | LF3 (0.30) | PR1 (0.13) |
| LF7 | LF6 (0.51) | LF8 (0.22) | LF3 (0.44) | PR1 (0.14) |
| LF8 | LF9 (0.68) | LF7 (0.21) | LF3 (0.46) | LF3 (0.14) |
| LF9 | LF6 (0.38) | LF8 (0.35) | LF3 (0.44) | PR1 (0.27) |
| LF10 | LF16 (0.10) | LF11 (0.35) | LF3 (0.63) | PR1 (0.32) |
| LF11 | LF16 (0.19) | LF16 (0.20) | LF3 (0.38) | PR1 (0.22) |
| LF12 | LF11 (0.33) | LF11 (0.32) | LF3 (0.22) | LF11 (0.27) |
| LF13 | LF15 (0.20) | LF11 (0.31) | LF3 (0.33) | PR1 (0.11) |
| LF14 | LF15 (0.82) | LF11 (0.31) | LF3 (0.19) | PR1 (0.19) |
| LF15 | LF14 (0.70) | LF14 (0.29) | LF3 (0.26) | LF11 (0.14) |
| LF16 | LF15 (0.49) | LF11 (0.36) | LF3 (0.46) | PR1 (0.17) |
| PR1 | PR2 (0.54) | PR4 (0.33) | LF3 (0.41) | PR2 (0.37) |
| PR2 | PR3 (0.47) | PR3 (0.51) | LF3 (0.31) | PR1 (0.26) |
| PR3 | PR1 (0.62) | PR4 (0.39) | LF3 (0.18) | PR1 (0.34) |
| PR4 | PR2 (0.48) | PR1 (0.34) | LF3 (0.43) | PR1 (0.53) |
| PR5 | LF11 (0.43) | PR3 (0.49) | LF3 (0.19) | PR2 (0.16) |

## First-pass observations (full flag breakdown deferred to the tournament report)

* **CONTRADICT overwhelmingly selects LF3**: 13 of 21 sources (62%), including every PR
  source. LF3 is destination for **24 of 84** picks total (28.6%) — a sharper attractor
  than either P1 or P3 were in the original field (14/80, 17.5%).
  * LF3, read cold: "It can't be. She can't believe it. Won't believe it..." — a page of
    blunt, short-sentence disbelief/refusal. It's plausible this reads as "in tension with"
    almost anything by virtue of its flat declarative negation, independent of specific
    content — worth checking in Phase B whether that's a real CONTRADICT signal or a
    positional/register attractor.
* **PR1 is a secondary attractor**, especially for BRIDGE (8 of 21 BRIDGE picks), 16/84
  overall (19%).
* **LF4's forward field is already fully CONTRADICT-attractor-dominated**: all four
  operators select LF3. This foreshadows Phase B's operator-invariant classification.

## Deduplication for Phase B

20 of 21 sources have 2+ unique forward destinations and are testable; **LF4** has exactly
one (LF3 for all four operators) and will be marked operator-invariant, not run. Total
Phase B calls: 80 (20 testable sources x 4 operators).
