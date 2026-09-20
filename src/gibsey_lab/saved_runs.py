"""Index of pre-existing recorded runs the reader app may display as 'recorded results'
without making a new call. Only matches the canonical original-field forward runs
(case_id prefix 'relop-holdout-full-') -- removal-condition, tournament, and reverse-typing
runs are deliberately excluded so they are never silently preloaded as if they were the
plain original-field result."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .recorder import RUNS_DIR

CANONICAL_PREFIX = "relop-holdout-full-"


@dataclass(frozen=True)
class SavedResult:
    run_dir: Path
    run_id: str
    field: str
    source_id: str
    operator: str
    criterion: str
    is_abstention: bool
    selected_id: str | None
    selected_text: str | None
    confidence: float | None
    probabilities: dict
    requested_model: str | None
    returned_model: str | None
    elapsed_seconds: float | None
    usage: dict


def _parse_case_id(case_id: str) -> tuple[str, str] | None:
    """'relop-holdout-full-PR1-develop' -> ('PR1', 'DEVELOP')."""
    if not case_id.startswith(CANONICAL_PREFIX):
        return None
    rest = case_id[len(CANONICAL_PREFIX):]
    parts = rest.rsplit("-", 1)
    if len(parts) != 2:
        return None
    source_id, operator_lower = parts
    return source_id, operator_lower.upper()


def find_saved_original_field_result(source_id: str, operator: str, runs_dir: Path = RUNS_DIR) -> SavedResult | None:
    """Look up the canonical Phase-A original-field result for (source_id, operator) in
    the holdout-21 field, if one was ever recorded. Returns None if not found -- never
    fabricates a result."""
    if not runs_dir.is_dir():
        return None
    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        input_path = run_dir / "input.json"
        if not input_path.exists():
            continue
        try:
            input_record = json.loads(input_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        parsed = _parse_case_id(input_record.get("case_id", ""))
        if parsed is None:
            continue
        found_source, found_operator = parsed
        if found_source != source_id or found_operator != operator:
            continue

        result = json.loads((run_dir / "result.json").read_text())
        response = json.loads((run_dir / "response.json").read_text())
        if result is None:
            continue  # a failed/error run; not usable as a recorded result
        return SavedResult(
            run_dir=run_dir,
            run_id=input_record["run_id"],
            field="holdout-21",
            source_id=found_source,
            operator=found_operator,
            criterion=input_record["criterion"],
            is_abstention=result["is_abstention"],
            selected_id=result["selected_id"],
            selected_text=result["selected_text"],
            confidence=result["confidence"],
            probabilities=result["probabilities"],
            requested_model=response.get("requested_model"),
            returned_model=response.get("returned_model"),
            elapsed_seconds=response.get("elapsed_seconds"),
            usage=response.get("usage") or {},
        )
    return None
