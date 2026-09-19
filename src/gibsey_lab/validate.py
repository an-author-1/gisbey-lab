from __future__ import annotations

from dataclasses import asdict, dataclass

from .context import ContextPacket
from .results import ChoiceResult


class ProviderResultError(Exception):
    pass


@dataclass(frozen=True)
class ValidatedOutcome:
    case_id: str
    is_abstention: bool
    selected_id: str | None
    selected_text: str | None
    confidence: float | None
    probabilities: dict[str, float]

    def to_dict(self) -> dict:
        return asdict(self)


def validate_choice_result(packet: ContextPacket, result: ChoiceResult) -> ValidatedOutcome:
    if result.choice not in packet.options:
        raise ProviderResultError(f"provider returned an option outside the permitted set: {result.choice!r}")

    unknown = [k for k in result.probabilities if k not in packet.options]
    if unknown:
        raise ProviderResultError(f"probabilities reference options outside the permitted set: {unknown}")

    is_abstention = result.choice == "NONE"
    selected_text = None if is_abstention else packet.options[result.choice]  # resolved in code, not by the model
    return ValidatedOutcome(
        case_id=packet.case_id,
        is_abstention=is_abstention,
        selected_id=None if is_abstention else result.choice,
        selected_text=selected_text,
        confidence=result.confidence,
        probabilities=dict(result.probabilities),
    )
