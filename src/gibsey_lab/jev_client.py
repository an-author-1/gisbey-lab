from __future__ import annotations

import time

from .config import Config
from .results import ChoiceResult


class JevError(Exception):
    pass


def run_choice(cfg: Config, *, state: str, instructions: str, criteria: dict[str, str]) -> ChoiceResult:
    """One real TypeSafe Choice call. Raises JevError on any failure; never returns a
    fabricated result. Never logs cfg.api_key or an Authorization header."""
    if not cfg.has_live_credentials:
        raise JevError("TYPESAFE_API_KEY is not set; cannot make a live Jev call")

    try:
        from typesafe_sdk import Choice, TypeSafeClient
    except ImportError as e:
        raise JevError(f"typesafe-sdk is not installed: {e}") from e

    start = time.monotonic()
    try:
        with TypeSafeClient() as client:
            response = client.system_one(
                state=state,
                model=cfg.model,
                questions={"destination": Choice(instructions=instructions, criteria=criteria)},
            )
    except Exception as e:  # network/provider error of unknown SDK-specific type
        raise JevError(f"{type(e).__name__}: {e}") from e
    elapsed = time.monotonic() - start

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
