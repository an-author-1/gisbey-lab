"""Gathers exact recorded source/destination text, operator, and criterion for the most
recent Q traversals, for an external review process (the "Review my latest reading
session" Claude Code command, which spawns read-only close-reader/skeptical-reader
subagents). Read-only: never mutates Q/R state, never writes review.json, never
constructs anything sent to Jev. Confidence/probabilities are deliberately left out of
the gathered material -- the agents review text, not the model's own score.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import fields as fields_module
from .session_log import DEFAULT_LOG_PATH, read_recent_traversals


def gather_recent_traversal_material(limit: int = 10, log_path: Path = DEFAULT_LOG_PATH) -> list[dict]:
    traversals = read_recent_traversals(limit=limit, log_path=log_path)
    material = []
    for t in traversals:
        run_dir = Path(t["run_dir"]) if t.get("run_dir") else None
        if run_dir is None or not run_dir.is_dir():
            continue
        try:
            input_record = json.loads((run_dir / "input.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue

        source_id = input_record.get("source_id")
        destination_id = t.get("destination")
        options = input_record.get("options") or {}
        corpus_hashes = input_record.get("corpus_hashes") or {}
        reader_state = input_record.get("reader_state") or {}
        field_id = t.get("field") or reader_state.get("field")

        destination_text = options.get(destination_id)

        source_text = None
        source_hash_verified = False
        if field_id in fields_module.KNOWN_FIELDS:
            try:
                field = fields_module.load_field(field_id)
                page = field.manifest.get(source_id)
                if page is not None and corpus_hashes.get(source_id) == page.sha256:
                    source_text = page.text
                    source_hash_verified = True
            except Exception:  # noqa: BLE001 -- best-effort; missing text is reported, not fatal
                pass

        material.append({
            "at": t.get("at"),
            "field": field_id,
            "source_id": source_id,
            "source_text": source_text,
            "source_hash_verified": source_hash_verified,
            "operator": t.get("operator") or reader_state.get("operator"),
            "criterion": input_record.get("criterion"),
            "destination_id": destination_id,
            "destination_text": destination_text,
            "run_dir": str(run_dir),
            "proposal_id": t.get("proposal_id"),
            "bond_id": t.get("bond_id"),
        })
    return material
