from __future__ import annotations

import re

from .results import ChoiceResult

_WORD = re.compile(r"[A-Za-z']+")


def _tokens(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text)}


def run_choice_mock(
    *, state: str, instructions: str, criteria: dict[str, str], option_order: list[str], model: str
) -> ChoiceResult:
    """Deterministic offline stand-in: scores each option by lexical token overlap with
    `state`. Not a literary judgment — only for exercising the harness without network
    access or spend. Always returns live=False so it can never be mistaken for a real
    Jev result downstream."""
    active_tokens = _tokens(state)
    scores: dict[str, float] = {}
    for opt_id in option_order:
        if opt_id == "NONE":
            scores[opt_id] = 0.5  # fixed modest baseline: neither dominant nor unreachable
            continue
        overlap = len(active_tokens & _tokens(criteria[opt_id]))
        scores[opt_id] = float(overlap) + 0.1

    total = sum(scores.values())
    probabilities = {k: v / total for k, v in scores.items()}
    choice = max(option_order, key=lambda k: probabilities[k])

    return ChoiceResult(
        requested_model=model,
        returned_model="mock-lexical-overlap-v1",
        choice=choice,
        confidence=probabilities[choice],
        probabilities=probabilities,
        usage={},
        elapsed_seconds=0.0,
        live=False,
    )
