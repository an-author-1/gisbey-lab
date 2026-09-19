# src/

Loader, context assembler, Jev adapter, proposal validator, run recorder, and reader-state handling.

Implemented as the `gibsey_lab` package: `corpus.py` (loader/manifest), `sentence_map.py`,
`cases.py` + `context.py` (case specs and assembly), `jev_client.py` (real adapter) /
`mock_client.py` (deterministic offline adapter), `validate.py`, `recorder.py`, `runner.py`,
`state.py` (Q/R actions), and `cli.py` (the `gibsey` command). See the root `README.md`,
"Implementation Status and Commands."
