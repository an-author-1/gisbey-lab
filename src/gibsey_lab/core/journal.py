"""Per-session append-only event journal: the authoritative record of a journey.

    data/core/sessions/<session_id>/events.jsonl

One committed event is ONE line written by one `write()` call after an exclusive file
lock, followed by fsync. A crash before the write leaves nothing; a crash after it leaves
a complete event. Every projection (reader_state.json, bonds.json, the session log's
mirror events) is derived from this file and can be rebuilt from it; the journal never
depends on them.

Event envelope (event-schema core-event/1):

    {"schema": "core-event/1", "seq": n, "session_id": ..., "at": iso-utc, "event": type,
     "revision_after": r, ...payload}

`seq` is the per-session event order (plan §4.5, "event order"); it is assigned here,
never by the caller. `revision_after` is the state revision once this event is applied:
it is computed by the pure reducer from the events before it, so the journal and the
reducer can be checked against each other.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

try:  # POSIX only; within one process the threading lock already serializes writers
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

from ..corpus import REPO_ROOT

SCHEMA = "core-event/1"
DEFAULT_CORE_DIR = REPO_ROOT / "data" / "core"

EVENT_TYPES = (
    "session_started",     # initial location: {version_id, page_id, sha256, text_sha256: same, via}
    "offer_set_created",   # persisted ordered offers at a revision: {offer_set_id, ...}
    "action_committed",    # accepted action: {request_id, offer_set_id, bond_version_id, from_version, to_version}
    "relocation_committed",  # accepted manual move (no bond, no operator): {request_id, cause, from_version, to_version}
    "action_rejected",     # recorded refusal (never changes state): {request_id, code, reason}
    "paused",
    "resumed",
    "performance_ended",
    "presented",           # reader-render acknowledgement of an offer set; not attention, not an encounter
)

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class JournalError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def session_dir(session_id: str, core_dir: Path = DEFAULT_CORE_DIR) -> Path:
    if not session_id or "/" in session_id or session_id in (".", ".."):
        raise JournalError(f"invalid session id: {session_id!r}")
    return core_dir / "sessions" / session_id


def journal_path(session_id: str, core_dir: Path = DEFAULT_CORE_DIR) -> Path:
    return session_dir(session_id, core_dir) / "events.jsonl"


def _lock_for(path: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(path), threading.Lock())


def read_events(session_id: str, core_dir: Path = DEFAULT_CORE_DIR) -> list[dict]:
    """All committed events, in seq order. A torn trailing line (a crash mid-write of a
    single line, which the single-write discipline makes very unlikely) is reported, not
    silently dropped."""
    path = journal_path(session_id, core_dir)
    if not path.exists():
        return []
    events: list[dict] = []
    raw = path.read_text(encoding="utf-8")
    for index, line in enumerate(raw.split("\n")):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as e:
            raise JournalError(f"{path}: line {index} is not valid JSON (torn write?): {e}") from e
        if event.get("seq") != len(events):
            raise JournalError(f"{path}: line {index} has seq {event.get('seq')}, expected {len(events)}")
        events.append(event)
    return events


def append(session_id: str, event_type: str, payload: dict, *, revision_after: int,
           core_dir: Path = DEFAULT_CORE_DIR, expected_seq: int | None = None) -> dict:
    """Atomically append one event. `expected_seq`, when given, must equal the next seq
    (optimistic check that the caller reduced the same history it is extending)."""
    if event_type not in EVENT_TYPES:
        raise JournalError(f"unknown event type: {event_type!r}")
    path = journal_path(session_id, core_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock_for(path):
        with open(path, "a+b") as f:
            if fcntl is not None:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.seek(0)
                existing = f.read()
                seq = sum(1 for line in existing.split(b"\n") if line.strip())
                if expected_seq is not None and seq != expected_seq:
                    raise JournalError(f"journal advanced: next seq is {seq}, caller expected {expected_seq}")
                record = {"schema": SCHEMA, "seq": seq, "session_id": session_id, "at": _now(),
                          "event": event_type, "revision_after": revision_after, **payload}
                line = json.dumps(record, ensure_ascii=False) + "\n"
                if existing and not existing.endswith(b"\n"):
                    line = "\n" + line  # heal a torn tail rather than gluing two records
                f.seek(0, os.SEEK_END)
                f.write(line.encode("utf-8"))  # one write: the event exists entirely or not at all
                f.flush()
                os.fsync(f.fileno())
            finally:
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return record


def list_sessions(core_dir: Path = DEFAULT_CORE_DIR) -> list[str]:
    root = core_dir / "sessions"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "events.jsonl").exists())
