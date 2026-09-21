from __future__ import annotations

import hashlib
import json
import time

from .config import Config
from .results import ChoiceResult


class JevError(Exception):
    pass


CHOICE_TIMEOUT_SECONDS = 30.0


def _estimate_choice_tokens(state: str, instructions: str, criteria: dict[str, str]) -> int:
    chars = len(state) + len(instructions) + sum(len(k) + len(v) for k, v in criteria.items())
    return int(chars / 3.0) + 64


def run_choice(cfg: Config, *, state: str, instructions: str, criteria: dict[str, str], ledger=None) -> ChoiceResult:
    """One real TypeSafe Choice call = exactly one HTTP attempt. Raises JevError on any
    failure; never returns a fabricated result. Never logs cfg.api_key or an
    Authorization header.

    The SDK's own hidden retries (typesafe-sdk defaults to 2) are disabled here, so the
    only retries are runner.MAX_RETRIES, each of which calls this function again. Every
    attempt is reserved in a budget ledger first (default: the interactive "reader"
    ledger, data/reader_ledger.jsonl); a refused reservation raises JevError without any
    network call. Until 2026-09-20 this path used SDK defaults and no ledger, so earlier
    runs' true HTTP attempt counts are unknown (at most 3 per recorded try)."""
    if not cfg.has_live_credentials:
        raise JevError("TYPESAFE_API_KEY is not set; cannot make a live Jev call")

    try:
        from typesafe_sdk import Choice, RetryPolicy, TypeSafeClient
    except ImportError as e:
        raise JevError(f"typesafe-sdk is not installed: {e}") from e

    if ledger is None:
        from . import live_gateway  # lazy: keeps this module importable without the atlas package

        ledger = live_gateway.ledger_for("reader")
    fingerprint = hashlib.sha256(
        json.dumps([state, instructions, criteria, cfg.model], sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    reservation = ledger.reserve(
        request_sha256=fingerprint, kind="operator_choice",
        est_input_tokens=_estimate_choice_tokens(state, instructions, criteria),
    )
    if reservation is None:
        raise JevError("the interactive budget ledger refused this request (a cap would be exceeded); no live call was made")

    start = time.monotonic()
    try:
        with TypeSafeClient(retry=RetryPolicy(max_retries=0, timeout=CHOICE_TIMEOUT_SECONDS)) as client:
            response = client.system_one(
                state=state,
                model=cfg.model,
                questions={"destination": Choice(instructions=instructions, criteria=criteria)},
            )
    except Exception as e:  # network/provider error of unknown SDK-specific type
        message = f"{type(e).__name__}: {e}"
        ledger.settle(reservation, ok=False, usage=None, returned_model=None, error=message)
        raise JevError(message) from e
    elapsed = time.monotonic() - start
    _usage = getattr(response, "usage", None)
    _usage = _usage.model_dump() if hasattr(_usage, "model_dump") else (dict(_usage) if _usage else None)
    ledger.settle(reservation, ok=True, usage=_usage, returned_model=getattr(response, "model", None), error=None)

    answers = getattr(response, "answers", None)
    if answers is None:
        answers = getattr(response, "choices", None)
    if answers is None:
        raise JevError("unrecognized response shape: no 'answers' or 'choices' attribute on the response")

    answer = answers.get("destination") if hasattr(answers, "get") else answers["destination"]
    if answer is None:
        raise JevError("response missing the 'destination' answer")

    choice = getattr(answer, "choice", None)
    if not choice or choice not in criteria:
        raise JevError(f"invalid choice returned by provider: {choice!r} is not among the permitted options")

    probabilities = dict(getattr(answer, "probabilities", None) or {})
    confidence = getattr(answer, "confidence", None)
    usage = dict(getattr(response, "usage", None) or {})
    returned_model = getattr(response, "model", None)

    return ChoiceResult(
        requested_model=cfg.model,
        returned_model=returned_model,
        choice=choice,
        confidence=confidence,
        probabilities=probabilities,
        usage=usage,
        elapsed_seconds=elapsed,
        live=True,
    )
