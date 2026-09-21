"""Public atlas API: computed views over the append-only assessment store, and the
resumable build.

Guarantees:
- The atlas is every directed non-self pair of the full-41 field: 41 x 40 = 1,640,
  authored neighbors included. A->B and B->A are separate entries. Discovery may filter
  neighbors at runtime; the base atlas never does.
- Pair status is computed on every call, never stored:
    complete   -- a record with status ok, all seven dimensions valid, both endpoint
                  hashes equal to the current manifest, and a matching config + mode.
                  A low score is a value, so an assessed-weak pair is `complete`.
    stale      -- only ok-records whose hashes / rubric / config / returned model no
                  longer match (history is kept; the pair is simply due again).
    failed     -- only error / invalid records.
    unassessed -- no record at all. Missing never means zero.
- Live and mock are separate views. A record counts only toward the view of the mode its
  dispatch stamped on it; a dispatch whose outcome mode disagrees with the requested mode
  raises before anything is written, so mock can never be stored as live.
- Records from a different returned model are never pooled with the pinned model's, and
  under a frozen config a record must also have REQUESTED the frozen requested model to
  be `complete` (requested_model is deliberately not part of `config_id`, so existing
  ids stay stable; the check is made when status is computed).
  `config_id` hashes schema + rubric version (and the rubric's exact wording) +
  dimension ids + state layout + pinned returned model. Each record's config_id is
  computed from the model that actually answered it.
- Before `freeze_config` has been called, the live config reports `frozen: false` and
  pins no model (pilot phase): a record is then compatible under the active rubric with
  whatever model returned it, and `coverage` lists every distinct returned model so a
  mix is visible. `build_missing(..., pinned_returned_model=...)` pins one explicitly.
- `build_missing` is checkpointed by construction: each pair is appended the moment it
  finishes, complete pairs are skipped, and an interrupted build resumes by being run
  again. It stops boundedly on persistent failure, on the first budget refusal, and on
  the first returned-model mismatch.
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import replace as _dc_replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from ..config import DEFAULT_MODEL
from ..fields import FULL_41, Field, load_field
from ..scoring import MOCK_MODEL, Dispatch
from . import store
from .rubrics import DIMENSIONS, RUBRIC_VERSION, STATE_LAYOUT, build_pair_request, get_rubric

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "data" / "atlas" / "active_config.json"
CONFIG_SCHEMA = "atlas-config/1"

FIELD_ID = FULL_41
LAYER = "base_pair_profile"
MODES = store.MODES
STATUSES = ("complete", "stale", "failed", "unassessed")
DEFAULT_REQUESTED_MODEL = DEFAULT_MODEL
MAX_CONCURRENCY = 2
MAX_CONSECUTIVE_FAILURES = 6  # consecutive non-ok outcomes (error or invalid) that end a build


class AtlasError(ValueError):
    pass


class AtlasModeError(AtlasError):
    """A dispatch answered in a different mode than the one the build was asked for."""


# --------------------------------------------------------------------------- field


def current_field() -> Field:
    return load_field(FIELD_ID)


def all_pairs(field: Field | None = None) -> list[tuple[str, str]]:
    """Every directed non-self pair, authored neighbors included (1,640 for full-41)."""
    ids = (field or current_field()).all_ids()
    return [(src, dst) for src in ids for dst in ids if src != dst]


# --------------------------------------------------------------------------- config


def compute_config_id(rubric_version: str, pinned_returned_model: str | None) -> str:
    rubric = get_rubric(rubric_version)
    blob = json.dumps(
        {
            "schema": store.SCHEMA,
            "rubric_version": rubric.version,
            "rubric_sha256": rubric.sha256,
            "dimensions": list(rubric.dimensions),
            "state_layout": STATE_LAYOUT,
            "pinned_returned_model": pinned_returned_model,
        },
        sort_keys=True, separators=(",", ":"),
    )
    return "cfg-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _config(mode: str, *, frozen: bool, rubric_version: str, requested_model: str, pinned: str | None, extra=None) -> dict:
    rubric = get_rubric(rubric_version)
    return {
        "schema": CONFIG_SCHEMA,
        "mode": mode,
        "frozen": frozen,
        "field": FIELD_ID,
        "rubric_version": rubric.version,
        "rubric_sha256": rubric.sha256,
        "dimensions": list(rubric.dimensions),
        "state_layout": STATE_LAYOUT,
        "requested_model": requested_model,
        "pinned_returned_model": pinned,
        "config_id": compute_config_id(rubric.version, pinned),
        **(extra or {}),
    }


def _read_config_file() -> dict | None:
    path = Path(CONFIG_PATH)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != CONFIG_SCHEMA or not isinstance(data.get("active"), dict):
        raise AtlasError(f"{path} is not an {CONFIG_SCHEMA} file")
    return data


def active_config(mode: str = "live") -> dict:
    if mode == "mock":
        return _config("mock", frozen=True, rubric_version=RUBRIC_VERSION,
                       requested_model=DEFAULT_REQUESTED_MODEL, pinned=MOCK_MODEL)
    if mode != "live":
        raise AtlasError(f"unknown mode: {mode!r}; known modes: {MODES}")
    data = _read_config_file()
    if data is None:
        return _config("live", frozen=False, rubric_version=RUBRIC_VERSION,
                       requested_model=DEFAULT_REQUESTED_MODEL, pinned=None)
    active = data["active"]
    return _config("live", frozen=True, rubric_version=active["rubric_version"],
                   requested_model=active["requested_model"], pinned=active["pinned_returned_model"],
                   extra={"frozen_at": active.get("frozen_at"), "note": active.get("note")})


def freeze_config(
    *, pinned_returned_model: str, requested_model: str, rubric_version: str = RUBRIC_VERSION,
    note: str | None = None, replace: bool = False,
) -> dict:
    """Pin the live assessment configuration (lead-only, after the pilot). Refuses to
    change an existing freeze unless `replace=True`, in which case the previous freeze
    moves into the file's `history` -- assessment records are never touched either way."""
    if not pinned_returned_model or pinned_returned_model == MOCK_MODEL:
        raise AtlasError("the live config must pin a real returned model id")
    if not requested_model:
        raise AtlasError("requested_model is required")
    get_rubric(rubric_version)
    wanted = {"rubric_version": rubric_version, "pinned_returned_model": pinned_returned_model,
              "requested_model": requested_model}
    data = _read_config_file() or {"schema": CONFIG_SCHEMA, "active": None, "history": []}
    current = data["active"]
    if current is not None:
        if {k: current.get(k) for k in wanted} == wanted:
            return active_config("live")
        if not replace:
            raise AtlasError(f"live atlas config is already frozen as {current}; pass replace=True to supersede it")
        data.setdefault("history", []).append(current)
    data["active"] = {
        **wanted,
        "frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": note,
        "config_id": compute_config_id(rubric_version, pinned_returned_model),
    }
    path = Path(CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return active_config("live")


def _build_config(mode: str, pinned_override: str | None) -> dict:
    cfg = active_config(mode)
    if pinned_override is None or pinned_override == cfg["pinned_returned_model"]:
        return cfg
    if mode == "mock":
        raise AtlasError(f"mock assessments are always pinned to {MOCK_MODEL!r}")
    if cfg["frozen"]:
        raise AtlasError(
            f"live config is frozen to {cfg['pinned_returned_model']!r}; refusing to build against "
            f"{pinned_override!r} (model versions are never mixed silently)"
        )
    return _config("live", frozen=False, rubric_version=cfg["rubric_version"],
                   requested_model=cfg["requested_model"], pinned=pinned_override)


# --------------------------------------------------------------------------- status


def _fully_valid(record: dict) -> bool:
    dims = record.get("dimensions") or {}
    return record.get("status") == "ok" and all(
        isinstance(dims.get(d), dict) and dims[d].get("valid") is True and dims[d].get("score") is not None
        for d in DIMENSIONS
    )


def _matches_config(record: dict, cfg: dict) -> bool:
    if record.get("rubric_version") != cfg["rubric_version"]:
        return False
    pinned = cfg["pinned_returned_model"]
    if pinned is None:  # unfrozen pilot: compatible with the active rubric under its own model
        return record.get("config_id") == compute_config_id(cfg["rubric_version"], record.get("returned_model"))
    if cfg["frozen"] and record.get("requested_model") != cfg["requested_model"]:
        return False  # a frozen config pins what was asked for as well as what answered
    return record.get("returned_model") == pinned and record.get("config_id") == cfg["config_id"]


def _mismatch_reasons(record: dict, cfg: dict, field: Field) -> list[str]:
    reasons = []
    if record.get("source_sha256") != field.manifest[record["source_id"]].sha256:
        reasons.append("source text changed since assessment")
    if record.get("destination_sha256") != field.manifest[record["destination_id"]].sha256:
        reasons.append("destination text changed since assessment")
    if record.get("rubric_version") != cfg["rubric_version"]:
        reasons.append(f"rubric {record.get('rubric_version')} != active {cfg['rubric_version']}")
    elif cfg["pinned_returned_model"] is not None and record.get("returned_model") != cfg["pinned_returned_model"]:
        reasons.append(f"returned model {record.get('returned_model')} != pinned {cfg['pinned_returned_model']}")
    elif cfg["frozen"] and cfg["pinned_returned_model"] is not None and record.get("requested_model") != cfg["requested_model"]:
        reasons.append(f"requested model {record.get('requested_model')} != frozen {cfg['requested_model']}")
    elif not _matches_config(record, cfg):
        reasons.append("assessment config differs from the active config")
    return reasons


def _records_by_pair(mode: str) -> tuple[dict[tuple[str, str], list[dict]], int]:
    records, corrupt = store.read_assessments()
    by_pair: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        if record.get("mode") != mode:
            continue  # the other mode's records are a different view, never pooled
        by_pair.setdefault((record["source_id"], record["destination_id"]), []).append(record)
    return by_pair, corrupt


def _classify(records: list[dict], cfg: dict, field: Field) -> tuple[str, dict | None]:
    """(status, latest compatible record). `records` are this pair's, this mode's, in
    file order."""
    if not records:
        return "unassessed", None
    src, dst = records[0]["source_id"], records[0]["destination_id"]
    current = (field.manifest[src].sha256, field.manifest[dst].sha256)
    for record in reversed(records):
        if (_fully_valid(record) and (record.get("source_sha256"), record.get("destination_sha256")) == current
                and _matches_config(record, cfg)):
            return "complete", record
    if any(_fully_valid(r) for r in records):
        return "stale", None
    return "failed", None


def _neighbor_relation(field: Field, source_id: str, destination_id: str) -> str | None:
    for relation, pid in field.neighbors_of(source_id).items():
        if pid == destination_id:
            return relation
    return None


def _profile_row(field: Field, cfg: dict, source_id: str, destination_id: str, records: list[dict]) -> dict:
    status, record = _classify(records, cfg, field)
    relation = _neighbor_relation(field, source_id, destination_id)
    latest = records[-1] if records else None
    row = {
        "layer": LAYER,
        "mode": cfg["mode"],
        "source_id": source_id,
        "destination_id": destination_id,
        "status": status,
        "is_authored_neighbor": relation is not None,
        "neighbor_relation": relation,
        "dimensions": None,
        "assessment_id": None,
        "source_sha256": field.manifest[source_id].sha256,
        "destination_sha256": field.manifest[destination_id].sha256,
        "rubric_version": cfg["rubric_version"],
        "config_id": cfg["config_id"],
        "returned_model": None,
        "record_count": len(records),
        "stale_reasons": [],
        "last_errors": [],
    }
    if record is not None:
        row["assessment_id"] = record["assessment_id"]
        row["returned_model"] = record.get("returned_model")
        row["config_id"] = record.get("config_id")
        row["dimensions"] = {
            d: {k: record["dimensions"][d].get(k) for k in ("score", "score_norm", "max_level", "confidence")}
            for d in DIMENSIONS
        }
    elif status == "stale":
        newest_ok = next(r for r in reversed(records) if _fully_valid(r))
        row["stale_reasons"] = _mismatch_reasons(newest_ok, cfg, field)
    elif status == "failed" and latest is not None:
        problems = [f"{d}: {p}" for d, v in (latest.get("dimensions") or {}).items() for p in v.get("problems") or []]
        row["last_errors"] = (list(latest.get("errors") or []) + problems)[:5]
    return row


def _require_pair(field: Field, source_id: str, destination_id: str) -> None:
    for pid in (source_id, destination_id):
        if pid not in field.manifest:
            raise AtlasError(f"{pid!r} is not a page of field {field.id!r}")
    if source_id == destination_id:
        raise AtlasError("the atlas has no self pairs")


def pair_status(source_id: str, destination_id: str, mode: str = "live") -> dict:
    """Status of one directed pair under the active config, with the latest compatible
    record in full (`record`, None unless complete) and the most recent record of any
    status (`latest_record`) for inspection."""
    field = current_field()
    _require_pair(field, source_id, destination_id)
    cfg = active_config(mode)
    by_pair, _ = _records_by_pair(mode)
    records = by_pair.get((source_id, destination_id), [])
    row = _profile_row(field, cfg, source_id, destination_id, records)
    _, record = _classify(records, cfg, field)
    row["record"] = record
    row["latest_record"] = records[-1] if records else None
    row["frozen"] = cfg["frozen"]
    return row


def profiles_for_source(source_id: str, mode: str = "live") -> list[dict]:
    """One row per other page of the field (exactly 40 for full-41), every status
    represented -- an unassessed or failed destination is a row, never an omission."""
    field = current_field()
    if source_id not in field.manifest:
        raise AtlasError(f"{source_id!r} is not a page of field {field.id!r}")
    cfg = active_config(mode)
    by_pair, _ = _records_by_pair(mode)
    return [
        _profile_row(field, cfg, source_id, dst, by_pair.get((source_id, dst), []))
        for dst in field.candidate_ids_for(source_id)
    ]


def _coverage(field: Field, cfg: dict, pairs: Iterable[tuple[str, str]]) -> dict:
    by_pair, corrupt = _records_by_pair(cfg["mode"])
    counts = {s: 0 for s in STATUSES}
    per_source: dict[str, dict[str, int]] = {}
    complete_models: set[str] = set()
    total = 0
    for src, dst in pairs:
        status, record = _classify(by_pair.get((src, dst), []), cfg, field)
        counts[status] += 1
        per_source.setdefault(src, {s: 0 for s in STATUSES})[status] += 1
        total += 1
        if record is not None and record.get("returned_model"):
            complete_models.add(record["returned_model"])
    seen_models = sorted({r["returned_model"] for rs in by_pair.values() for r in rs if r.get("returned_model")})
    return {
        "layer": LAYER,
        "mode": cfg["mode"],
        "field": field.id,
        "total_pairs": total,
        "counts": counts,
        "per_source": per_source,
        "returned_models": sorted(complete_models),
        "returned_models_seen_in_store": seen_models,
        "mixed_returned_models": len(complete_models) > 1,
        "config": cfg,
        "records_in_mode": sum(len(rs) for rs in by_pair.values()),
        "corrupt_lines_skipped": corrupt,
    }


def coverage(mode: str = "live") -> dict:
    """Counts over all 1,640 directed pairs for one mode. `is_complete_live_atlas` is true
    only for a frozen live config with every pair complete under one returned model."""
    field = current_field()
    cfg = active_config(mode)
    result = _coverage(field, cfg, all_pairs(field))
    result["is_complete_live_atlas"] = (
        mode == "live" and cfg["frozen"] and result["counts"]["complete"] == result["total_pairs"]
        and not result["mixed_returned_models"]
    )
    return result


def last_job() -> dict | None:
    """Mode and job id of the most recently recorded assessment (for `atlas-resume`)."""
    records, _ = store.read_assessments()
    if not records:
        return None
    return {"mode": records[-1]["mode"], "job_id": records[-1].get("job_id")}


# --------------------------------------------------------------------------- build


def _new_job_id(mode: str) -> str:
    return f"atlas-{mode}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"


def build_missing(
    dispatch: Dispatch, mode: str, *, limit: int | None = None, pairs: Iterable[tuple[str, str]] | None = None,
    concurrency: int = MAX_CONCURRENCY, job_id: str | None = None, requested_model: str | None = None,
    pinned_returned_model: str | None = None, on_progress: Callable[[dict], None] | None = None,
) -> dict:
    """Assess every targeted pair that is not already `complete` under the active config.
    Resumable: run it again and it continues where the store says it left off."""
    if mode not in MODES:
        raise AtlasError(f"unknown mode: {mode!r}; known modes: {MODES}")
    field = current_field()
    cfg = _build_config(mode, pinned_returned_model)
    requested_model = requested_model or cfg["requested_model"]
    if cfg["frozen"] and requested_model != cfg["requested_model"]:
        raise AtlasError(
            f"{mode} config is frozen to requested model {cfg['requested_model']!r}; records requested as "
            f"{requested_model!r} could never be complete under it, so nothing was dispatched"
        )
    job_id = job_id or _new_job_id(mode)
    workers = max(1, min(int(concurrency), MAX_CONCURRENCY))

    targets = list(dict.fromkeys(tuple(p) for p in pairs)) if pairs is not None else all_pairs(field)
    for src, dst in targets:
        _require_pair(field, src, dst)

    by_pair, _ = _records_by_pair(mode)
    todo = [p for p in targets if _classify(by_pair.get(p, []), cfg, field)[0] != "complete"]
    skipped_complete = len(targets) - len(todo)
    truncated = limit is not None and len(todo) > max(0, limit)
    if limit is not None:
        todo = todo[: max(0, limit)]

    lock = threading.Lock()
    stop = threading.Event()
    queue = iter(todo)
    tally = {"attempted": 0, "ok": 0, "invalid": 0, "error": 0, "model_mismatch": 0}
    shared: dict = {"consecutive_failures": 0, "stopped_reason": None, "exception": None}

    def halt(reason: str) -> None:
        if shared["stopped_reason"] is None:
            shared["stopped_reason"] = reason
        stop.set()

    def work() -> None:
        while not stop.is_set():
            with lock:
                pair = next(queue, None)
            if pair is None:
                return
            source, destination = field.manifest[pair[0]], field.manifest[pair[1]]
            request = build_pair_request(source, destination, requested_model, rubric_version=cfg["rubric_version"])
            try:
                outcome = dispatch(request)
                if outcome.mode != mode:
                    raise AtlasModeError(
                        f"dispatch answered in mode {outcome.mode!r} but the build was asked for {mode!r}; "
                        "nothing was recorded (mock results are never stored as live, or the reverse)"
                    )
                if outcome.status == "budget_refused":
                    with lock:
                        halt("budget_refused")
                    return
                status = outcome.status
                errors = list(outcome.errors)
                if outcome.request_sha256 != request.request_sha256():
                    status = "invalid" if status == "ok" else status
                    errors.append("outcome request_sha256 does not match the request that was built")
                if status != outcome.status or errors != list(outcome.errors):
                    outcome = _dc_replace(outcome, status=status, errors=errors)
                record_config = (
                    compute_config_id(cfg["rubric_version"], outcome.returned_model)
                    if outcome.returned_model else cfg["config_id"]
                )
                record = store.build_record(
                    job_id=job_id, source=source, destination=destination, rubric_version=cfg["rubric_version"],
                    config_id=record_config, request=request, outcome=outcome,
                )
                store.append_assessment(record)
            except BaseException as e:  # noqa: BLE001 -- surfaced to the caller after the pool drains
                with lock:
                    if shared["exception"] is None:
                        shared["exception"] = e
                    halt("exception")
                return

            pinned = cfg["pinned_returned_model"]
            mismatch = bool(pinned and outcome.returned_model and outcome.returned_model != pinned)
            with lock:
                tally["attempted"] += 1
                tally[outcome.status] += 1
                if mismatch:
                    tally["model_mismatch"] += 1
                    halt("returned_model_mismatch")
                if outcome.status == "ok":
                    shared["consecutive_failures"] = 0
                else:
                    shared["consecutive_failures"] += 1
                    if shared["consecutive_failures"] >= MAX_CONSECUTIVE_FAILURES:
                        halt("consecutive_errors")
                snapshot = {"job_id": job_id, "pair": pair, "status": outcome.status, **tally, "of": len(todo)}
            if on_progress is not None:
                on_progress(snapshot)

    threads = [threading.Thread(target=work, name=f"atlas-build-{i}", daemon=True) for i in range(workers)]
    for t in threads:
        t.start()
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:  # let in-flight requests finish and be recorded, then stop
        halt("interrupted")
        for t in threads:
            t.join()
        raise
    if shared["exception"] is not None:
        raise shared["exception"]

    after = _coverage(field, cfg, targets)
    stopped_reason = shared["stopped_reason"]
    if stopped_reason is None and truncated:
        stopped_reason = "limit"
    return {
        "job_id": job_id,
        "mode": mode,
        "config_id": cfg["config_id"],
        "frozen": cfg["frozen"],
        "requested_model": requested_model,
        "pinned_returned_model": cfg["pinned_returned_model"],
        "targeted": len(targets),
        "skipped_complete": skipped_complete,
        **tally,
        "stopped_reason": stopped_reason,
        "remaining": after["total_pairs"] - after["counts"]["complete"],
        "returned_models": after["returned_models"],
        "resume_command": "gibsey atlas-resume",
    }
