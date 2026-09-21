"""The one place a ledgered live Score dispatch is constructed.

Two ledger scopes, both append-only and both enforced by atlas.ledger.Ledger (which never
allows limits looser than its module caps of 2,000 attempts / 10M input tokens / 2 in
flight):

- "milestone": data/atlas/ledger.jsonl -- pilot, atlas build, and the PR2 memory
  demonstration. This is the aggregate allowance set for the atlas/memory milestone; it
  is never reset by a restart or resume.
- "reader": data/reader_ledger.jsonl -- interactive requests made from the browser
  reader: offer hands (at most 8 contextual requests per explicit click) and operator
  Choice requests (jev_client.run_choice, one attempt each). Kept separate so
  ordinary reading does not silently fail once the milestone allowance is spent, and
  capped more strictly. Raise or lower with GIBSEY_READER_MAX_ATTEMPTS /
  GIBSEY_READER_MAX_INPUT_TOKENS (values above the module caps are clamped by Ledger).

The requested model and the pinned returned model come from the frozen atlas config
(data/atlas/active_config.json). Before the config is frozen, the configured model
(TYPESAFE_MODEL, default jev-latest) is requested and no returned model is enforced --
that is the pilot state. Pooling is decided by compatibility, not by timing: the v1-rubric
pilot records (requested jev-latest) are never counted, while the eight v2 re-pilot
records made seconds before the freeze ARE counted in the 1,640 because they were made
with the identical rubric, questions, requested and returned model, and config_id.
"""
from __future__ import annotations

import os
from pathlib import Path

from .atlas import api as atlas_api
from .atlas import ledger as ledger_module
from .config import load_config
from .scoring import Dispatch, make_live_dispatch

READER_LEDGER_PATH = ledger_module.REPO_ROOT / "data" / "reader_ledger.jsonl"
READER_DEFAULT_MAX_ATTEMPTS = 600
READER_DEFAULT_MAX_INPUT_TOKENS = 2_000_000

_ledgers: dict[str, ledger_module.Ledger] = {}


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


def ledger_for(scope: str) -> ledger_module.Ledger:
    if scope not in _ledgers:
        if scope == "milestone":
            _ledgers[scope] = ledger_module.Ledger(ledger_module.LEDGER_PATH)
        elif scope == "reader":
            _ledgers[scope] = ledger_module.Ledger(
                Path(READER_LEDGER_PATH),
                max_attempts=_int_env("GIBSEY_READER_MAX_ATTEMPTS", READER_DEFAULT_MAX_ATTEMPTS),
                max_input_tokens=_int_env("GIBSEY_READER_MAX_INPUT_TOKENS", READER_DEFAULT_MAX_INPUT_TOKENS),
            )
        else:
            raise ValueError(f"unknown ledger scope: {scope!r}")
    return _ledgers[scope]


def live_models() -> tuple[str, str | None]:
    """(requested_model, pinned_returned_model) for live work right now."""
    active = atlas_api.active_config("live")
    if active.get("frozen"):
        return active["requested_model"], active["pinned_returned_model"]
    return load_config().model, None


def live_dispatch(scope: str = "milestone") -> tuple[Dispatch, str]:
    """Returns (dispatch, requested_model). Raises RuntimeError without credentials so a
    missing key is a visible failure, never a silent fall back to mock."""
    cfg = load_config()
    if not cfg.has_live_credentials:
        raise RuntimeError("TYPESAFE_API_KEY is not configured; cannot make a live request. No live call was made.")
    requested, pinned = live_models()
    return make_live_dispatch(cfg, ledger_for(scope), expected_returned_model=pinned), requested


def wire_cli_hooks() -> None:
    """Point the atlas and memory CLI factories at the milestone-ledgered dispatch."""
    from .atlas import cli as atlas_cli
    from .memory import cli as memory_cli

    atlas_cli.LIVE_DISPATCH_FACTORY = lambda: live_dispatch("milestone")[0]
    memory_cli.LIVE_DISPATCH_FACTORY = lambda: live_dispatch("milestone")


def reader_offer_dispatch_factory() -> tuple[Dispatch, str, str]:
    """For reader.server.OFFER_DISPATCH_FACTORY: (dispatch, mode, requested_model)."""
    dispatch, requested = live_dispatch("reader")
    return dispatch, "live", requested
