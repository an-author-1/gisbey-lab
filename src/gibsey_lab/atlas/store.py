"""Append-only store of base pair assessments (`atlas-assessment/1`).

Guarantees:
- One JSONL line per provider outcome. Nothing is ever rewritten or deleted; "current"
  status is a computed view in `atlas.api`, never stored here.
- Each record carries the exact model-visible `state` and `questions` that were sent,
  the per-dimension raw answer (score, distribution, confidence, legend, validation
  problems), usage, timing, attempts and errors -- enough to re-audit the assessment
  without the corpus or the rubric module.
- `dimensions` only ever holds Layer 1 Score answers. Field-relative Choice history
  (Layer 2) lives elsewhere and is rejected here by construction.
- Appends are thread-safe (lock + flush + fsync). The reader is tolerant: corrupt lines
  are skipped and counted, and a half-written trailing line is left for the next read.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..corpus import Page
from ..scoring import ScoreOutcome, ScoreRequest
from .rubrics import DIMENSIONS

REPO_ROOT = Path(__file__).resolve().parents[3]
ASSESSMENTS_PATH = REPO_ROOT / "data" / "atlas" / "assessments.jsonl"

SCHEMA = "atlas-assessment/1"
RECORD_STATUSES = ("ok", "invalid", "error")
MODES = ("live", "mock")

REQUIRED_KEYS = (
    "schema", "assessment_id", "at", "job_id", "mode", "source_id", "destination_id",
    "source_sha256", "destination_sha256", "rubric_version", "config_id", "requested_model",
    "returned_model", "request_sha256", "state", "questions", "status", "dimensions", "usage",
    "elapsed_seconds", "attempts", "errors",
)

_DIMENSION_KEYS = ("score", "score_norm", "max_level", "confidence", "probabilities", "valid", "problems")

_lock = threading.Lock()
# path -> {"ident": (dev, ino), "offset": int, "records": list, "corrupt": int}
_cache: dict[str, dict] = {}


class StoreError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def build_record(
    *, job_id: str, source: Page, destination: Page, rubric_version: str, config_id: str,
    request: ScoreRequest, outcome: ScoreOutcome,
) -> dict:
    """Assemble one record from what was actually sent and what actually came back.
    `mode` is the outcome's own stamp -- the caller's intent is never recorded as mode."""
    if outcome.status not in RECORD_STATUSES:
        raise StoreError(f"outcome status {outcome.status!r} is not an assessment (nothing was assessed)")
    for role, page in (("source_page", source), ("destination_page", destination)):
        sent = request.state[role]["text"]
        if hashlib.sha256(sent.encode("utf-8")).hexdigest() != page.sha256:
            raise StoreError(f"text sent as {role} does not hash to the manifest sha256 of {page.id}")

    dimensions = {}
    for dim in DIMENSIONS:
        answer = outcome.answers.get(dim)
        if answer is None:
            continue
        full = answer.to_dict()
        dimensions[dim] = {k: full[k] for k in _DIMENSION_KEYS}
        dimensions[dim]["legend"] = full["legend"]

    return {
        "schema": SCHEMA,
        "assessment_id": f"as-{uuid.uuid4().hex}",
        "at": _now(),
        "job_id": job_id,
        "mode": outcome.mode,
        "source_id": source.id,
        "destination_id": destination.id,
        "source_sha256": source.sha256,
        "destination_sha256": destination.sha256,
        "rubric_version": rubric_version,
        "config_id": config_id,
        "requested_model": outcome.requested_model,
        "returned_model": outcome.returned_model,
        "request_sha256": request.request_sha256(),
        "state": request.state,
        "questions": [q.to_dict() for q in request.questions],
        "status": outcome.status,
        "dimensions": dimensions,
        "usage": outcome.usage,
        "elapsed_seconds": outcome.elapsed_seconds,
        "attempts": outcome.attempts,
        "errors": list(outcome.errors),
        "ledger_ids": list(outcome.ledger_ids),
    }


def _check(record: dict) -> None:
    missing = [k for k in REQUIRED_KEYS if k not in record]
    if missing:
        raise StoreError(f"assessment record is missing keys: {missing}")
    if record["schema"] != SCHEMA:
        raise StoreError(f"unexpected schema: {record['schema']!r}")
    if record["mode"] not in MODES:
        raise StoreError(f"unexpected mode: {record['mode']!r}")
    if record["status"] not in RECORD_STATUSES:
        raise StoreError(f"unexpected status: {record['status']!r}")
    if record["source_id"] == record["destination_id"]:
        raise StoreError("self pairs are not part of the atlas")
    foreign = [d for d in record["dimensions"] if d not in DIMENSIONS]
    if foreign:
        raise StoreError(f"dimensions may only hold the base rubric dimensions, got: {foreign}")
    for dim, value in record["dimensions"].items():
        if not isinstance(value, dict) or value.get("layer") not in (None, "base_pair_profile"):
            raise StoreError(f"dimension {dim!r} is not a Layer 1 Score answer")


def append_assessment(record: dict) -> None:
    _check(record)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    path = Path(ASSESSMENTS_PATH)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())


def read_assessments() -> tuple[list[dict], int]:
    """All readable records in file order, plus the number of corrupt lines skipped.
    Incremental: only bytes appended since the last read are parsed. The returned list is
    a fresh list of shared record dicts -- treat the records as read-only."""
    path = Path(ASSESSMENTS_PATH)
    key = str(path)
    with _lock:
        try:
            stat = path.stat()
        except FileNotFoundError:
            _cache.pop(key, None)
            return [], 0
        ident = (stat.st_dev, stat.st_ino)
        entry = _cache.get(key)
        if entry is None or entry["ident"] != ident or stat.st_size < entry["offset"]:
            entry = {"ident": ident, "offset": 0, "records": [], "corrupt": 0}
            _cache[key] = entry
        if stat.st_size > entry["offset"]:
            with open(path, "rb") as f:
                f.seek(entry["offset"])
                chunk = f.read()
            end = chunk.rfind(b"\n") + 1  # a trailing partial line stays unread for now
            for raw in chunk[:end].split(b"\n"):
                if not raw.strip():
                    continue
                try:
                    record = json.loads(raw.decode("utf-8"))
                    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
                        raise ValueError("not an atlas assessment record")
                    if any(k not in record for k in ("mode", "source_id", "destination_id", "status")):
                        raise ValueError("missing identifying keys")
                except (ValueError, UnicodeDecodeError):
                    entry["corrupt"] += 1
                    continue
                entry["records"].append(record)
            entry["offset"] += end
        return list(entry["records"]), entry["corrupt"]
