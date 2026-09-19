# tests/

Meaningful checks for corpus integrity, eligibility, and state preservation.

Pytest suite for the `gibsey_lab` package: corpus integrity/hashing, sentence-map proposal,
case eligibility (including refusing to build a case from missing/empty source text),
response validation, the deterministic mock adapter, config loading (credential handling),
and the propose/accept/follow/preserve state machine (repeat-safety, abstention handling).
Run with `.venv/bin/python -m pytest -q`.
