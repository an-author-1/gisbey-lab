"""Layer 2: historical field-relative Choice evidence, read-only.

Every row here comes from a saved Choice run under `recorder.RUNS_DIR`, in which one
source was shown a *set of competing candidates* and the model distributed probability
across that set. Such a probability is relative to that request's field, candidate
policy, criterion wording, candidate count, and NONE option -- it is not an independent
assessment of the pair, and two rows are only comparable when all of those match.

Guarantees:
- Read-only. Nothing under runs/ is written, moved, or re-labelled.
- Every row is labeled `layer: "field_relative_choice"` and carries its own provenance
  (run id, field, policy, criteria version, operator, candidate count, NONE option,
  requested/returned model, live flag). Rows have no `dimensions` key, and nothing in
  `atlas.api` reads this module: Choice probabilities never become Layer 1 values.
- Legacy runs that predate the reader record no field/policy/criteria version. Their
  field is inferred exactly as `saved_runs` infers it, and the inference is flagged;
  unrecorded policy/version are reported as such, not guessed into a current label.
- `relop-reverse` runs (relative operator typing of one given pair) are also Layer 2:
  exposed with `row_kind: "reverse_operator_typing"`, never as a pair score.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from .. import recorder
from ..relational_operators import CRITERIA_BY_VERSION
from ..saved_runs import _infer_legacy_field

LAYER = "field_relative_choice"
POLICY_UNRECORDED = "legacy-unrecorded"
CRITERIA_UNVERSIONED = "legacy-unversioned"

_PAGE_ID = re.compile(r"^[A-Za-z]+\d+$")
_lock = threading.Lock()
_cache: dict[tuple[str, str], dict | None] = {}  # (runs_dir, run name) -> slim run; saved runs are immutable


def _criteria_version(reader_state: dict, criterion: str | None) -> str:
    if reader_state.get("criteria_version"):
        return reader_state["criteria_version"]
    for version, criteria in CRITERIA_BY_VERSION.items():
        if criterion in criteria.values():
            return version
    return CRITERIA_UNVERSIONED


def _load_run(run_dir: Path) -> dict | None:
    try:
        input_record = json.loads((run_dir / "input.json").read_text(encoding="utf-8"))
        response = json.loads((run_dir / "response.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(input_record, dict) or not isinstance(response, dict):
        return None
    probabilities = response.get("probabilities")
    if not isinstance(probabilities, dict) or response.get("error"):
        return None  # a failed run holds no distribution
    reader_state = input_record.get("reader_state") or {}
    option_order = [str(o) for o in (input_record.get("option_order") or [])]
    source_id = str(input_record.get("source_id"))

    reverse = reader_state.get("task") == "reverse-operator-typing"
    if reverse:
        source_id = str(reader_state.get("source_page"))
        candidates = [str(reader_state.get("destination_page"))]
    else:
        candidates = [o for o in option_order if o != "NONE"]
        if input_record.get("active_id") or not all(_PAGE_ID.match(c) for c in candidates):
            return None  # sentence-level request: not a page-to-page Choice
    if not _PAGE_ID.match(source_id) or not candidates:
        return None

    recorded_field = reader_state.get("field")
    return {
        "run_id": input_record.get("run_id") or run_dir.name,
        "row_kind": "reverse_operator_typing" if reverse else "destination_choice",
        "source_id": source_id,
        "candidates": candidates,
        "field": recorded_field or _infer_legacy_field(candidates, source_id),
        "field_inferred": not recorded_field,
        "policy": reader_state.get("policy") or POLICY_UNRECORDED,
        "criteria_version": "reverse-typing" if reverse else _criteria_version(reader_state, input_record.get("criterion")),
        "operator": reader_state.get("operator"),
        "task": reader_state.get("task") or ("reader" if reader_state.get("app") == "reader" else None),
        "option_count": len(option_order),
        "had_none_option": "NONE" in option_order,
        "probabilities": probabilities,
        "choice": response.get("choice"),
        "request_confidence": response.get("confidence"),
        "requested_model": response.get("requested_model"),
        "returned_model": response.get("returned_model"),
        "live": response.get("live") is True,
    }


def _runs() -> list[dict]:
    runs_dir = Path(recorder.RUNS_DIR)
    if not runs_dir.is_dir():
        return []
    runs = []
    with _lock:
        for run_dir in sorted(runs_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            key = (str(runs_dir), run_dir.name)
            if key not in _cache:
                if not (run_dir / "response.json").exists():
                    continue  # still being written; look again next time
                _cache[key] = _load_run(run_dir)
            if _cache[key] is not None:
                runs.append(_cache[key])
    return runs


def _row(run: dict, destination_id: str) -> dict:
    row = {
        "layer": LAYER,
        "row_kind": run["row_kind"],
        "run_id": run["run_id"],
        "source_id": run["source_id"],
        "destination_id": destination_id,
        "field": run["field"],
        "field_inferred": run["field_inferred"],
        "policy": run["policy"],
        "criteria_version": run["criteria_version"],
        "operator": run["operator"],
        "task": run["task"],
        "had_none_option": run["had_none_option"],
        "request_confidence": run["request_confidence"],
        "requested_model": run["requested_model"],
        "returned_model": run["returned_model"],
        "live": run["live"],
    }
    if run["row_kind"] == "reverse_operator_typing":
        # The competing options were operator labels for this one pair, not destinations.
        row.update({
            "candidate_count": run["option_count"] - (1 if run["had_none_option"] else 0),
            "probability": None,
            "selected": None,
            "operator_probabilities": run["probabilities"],
            "selected_operator": run["choice"],
        })
    else:
        row.update({
            "candidate_count": len(run["candidates"]),
            "probability": run["probabilities"].get(destination_id),
            "selected": run["choice"] == destination_id,
            "request_choice": run["choice"],
        })
    return row


def choice_rows_for_pair(source_id: str, destination_id: str) -> list[dict]:
    """Every saved Choice request in which `destination_id` competed as a candidate for
    `source_id`, oldest first. Field-relative evidence only."""
    return [
        _row(run, destination_id)
        for run in _runs()
        if run["source_id"] == source_id and destination_id in run["candidates"]
    ]


def choice_rows_for_source(source_id: str) -> list[dict]:
    """One row per (saved Choice request, candidate) for `source_id`, oldest first."""
    return [_row(run, dst) for run in _runs() if run["source_id"] == source_id for dst in run["candidates"]]
