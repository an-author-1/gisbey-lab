from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChoiceResult:
    requested_model: str
    returned_model: str | None
    choice: str
    confidence: float | None
    probabilities: dict[str, float] = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    live: bool = True
