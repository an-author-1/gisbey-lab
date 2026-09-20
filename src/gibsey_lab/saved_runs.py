"""Lookup of pre-existing recorded runs the reader app may display as a 'recorded'
result without making a new call.

A saved run is only reused when its field, source page version, candidate set/versions/
order, operator criterion text, and requested model configuration all exactly match what
the current field/source/operator would produce right now. A result recorded under the
21-page holdout field is never presented as a result for the 41-page field, and a mock
run is never presented as a live recorded result -- both are structural checks, not
naming conventions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .fields import HOLDOUT_21, Field, prefix_of
from .recorder import RUNS_DIR

_HOLDOUT_PREFIXES = {"LF", "PR"}


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


def _infer_legacy_field(option_order: list[str], source_id: str) -> str:
    """Runs recorded before the reader app existed have no reader_state.field. Their
    field is inferred from their actual candidate set: all-holdout candidates means the
    21-page field; anything else (the pre-holdout training-only experiments) is tagged
    with a sentinel that can never equal either current field id, so it is correctly
    excluded rather than misattributed to full-41."""
    candidate_prefixes = {prefix_of(pid) for pid in option_order if pid != "NONE"}
    candidate_prefixes.add(prefix_of(source_id))
    if candidate_prefixes <= _HOLDOUT_PREFIXES:
        return HOLDOUT_21
    return "legacy-training-only-field"


def _expected_fingerprint(field: Field, source_id: str, operator: str, criterion: str) -> dict:
    candidate_order = field.candidate_ids_for(source_id)
    return {
        "field": field.id,
        "source_id": source_id,
        "operator": operator,
        "criterion": criterion,
        "source_hash": field.manifest[source_id].sha256,
        "candidate_order": candidate_order,
        "candidate_hashes": {pid: field.manifest[pid].sha256 for pid in candidate_order},
    }


def _actual_fingerprint(input_record: dict, corpus_hashes: dict) -> dict:
    reader_state = input_record.get("reader_state") or {}
    source_id = input_record["source_id"]
    option_order = input_record.get("option_order") or []
    candidate_order = [pid for pid in option_order if pid != "NONE"]
    field_id = reader_state.get("field") or _infer_legacy_field(option_order, source_id)
    operator = reader_state.get("operator")
    return {
        "field": field_id,
        "source_id": source_id,
        "operator": operator,
        "criterion": input_record.get("criterion"),
        "source_hash": corpus_hashes.get(source_id),
        "candidate_order": candidate_order,
        "candidate_hashes": {pid: corpus_hashes.get(pid) for pid in candidate_order},
    }


def find_matching_recorded_result(
    field: Field,
    source_id: str,
    operator: str,
    criterion: str,
    expected_model: str | None,
    runs_dir: Path = RUNS_DIR,
) -> SavedResult | None:
    """Search all recorded runs (both the original experiment batches and anything the
    reader app itself has produced) for one whose full fingerprint -- field, exact
    source/candidate versions and order, exact criterion text, and requested model --
    matches what would be sent right now. Returns the most recent qualifying match, or
    None if there isn't one. Never returns a mock run."""
    if not runs_dir.is_dir():
        return None

    expected = _expected_fingerprint(field, source_id, operator, criterion)
    best: SavedResult | None = None
    best_run_id = ""

    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        input_path = run_dir / "input.json"
        if not input_path.exists():
            continue
        try:
            input_record = json.loads(input_path.read_text())
            response = json.loads((run_dir / "response.json").read_text())
            result = json.loads((run_dir / "result.json").read_text())
        except (json.JSONDecodeError, OSError):
            continue

        if result is None:
            continue  # failed/error run: nothing usable to reuse
        if response.get("live") is not True:
            continue  # never surface a mock run as a "recorded" result

        actual = _actual_fingerprint(input_record, input_record.get("corpus_hashes") or {})
        if actual != expected:
            continue
        if expected_model is not None and response.get("requested_model") != expected_model:
            continue

        run_id = input_record.get("run_id", run_dir.name)
        if run_id <= best_run_id:
            continue  # keep the most recent qualifying match (run_ids sort chronologically)
        best_run_id = run_id
        best = SavedResult(
            run_dir=run_dir,
            run_id=run_id,
            field=actual["field"],
            source_id=source_id,
            operator=operator,
            criterion=criterion,
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

    return best
