"""Gibsey Core (v0.3): the transactional boundary for reader actions.

Layers, in dependency order and kept separate on purpose:

- identity   immutable content-version and bond-version references (pure)
- journal    per-session append-only event log; one committed event = one atomic append
- reducer    pure fold of events into reader state (no I/O, no clock, no provider)
- core       resolve_options / execute_action / resume_session / get_action_status:
             validation, request deduplication, atomic commit, then projections

Nothing in this package calls a model. The relationship atlas is read as a frozen input.
Inspection reads the journal; it never writes to it.
"""
