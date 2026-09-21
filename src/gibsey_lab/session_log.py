"""Automatic, passive session-route log: which pages were viewed, which field/operator
was active, which run records were shown or used, and Q traversal/backtracking.

Requires no written notes -- every event here is appended automatically by the reader
app as a side effect of normal navigation and Jev requests. Never preserves anything into
the Gibsey Vault on its own (that stays a separate, explicit action via state.preserve).
Kept out of Jev's Choice input entirely: nothing in this module is ever read by
jev_client or mock_client, and no code path here constructs a provider request.

Guarantees:
- Append-only. No function here rewrites, reorders, or deletes a line. Back navigation is
  a new `back` event; it never removes the encounters it walks back over.
- Every new event carries a monotonically increasing integer `seq` equal to its 0-based
  line index in the file, so numbering continues from legacy lines (which carry no `seq`)
  without touching them. `read_events_with_seq` supplies the same index for legacy lines
  at read time only.
- Appends are serialized by a process-wide lock (the reader runs a ThreadingHTTPServer).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from .corpus import REPO_ROOT

DEFAULT_LOG_PATH = REPO_ROOT / "data" / "session_log.jsonl"

# Legacy traversal event name. Still emitted alongside the newer, finer-grained
# proposal/acceptance/traversal events because session_review.read_recent_traversals and
# the memory packet's legacy path both read it.
TRAVERSAL_EVENT = "accept_and_follow"
Q_TRAVERSAL_EVENT = "q_traversal"

_APPEND_LOCK = threading.Lock()
# path -> (file size after our last append, line count). Lets an append skip recounting
# the file unless something else (another process, a test) wrote to it in between.
_LINE_COUNTS: dict[str, tuple[int, int]] = {}


def _count_lines(log_path: Path) -> int:
    if not log_path.exists():
        return 0
    with open(log_path, "r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _next_seq(log_path: Path) -> int:
    key = str(log_path)
    size = log_path.stat().st_size if log_path.exists() else 0
    cached = _LINE_COUNTS.get(key)
    if cached is not None and cached[0] == size:
        return cached[1]
    return _count_lines(log_path)


def append_event(event_type: str, log_path: Path = DEFAULT_LOG_PATH, **fields) -> dict:
    log_path = Path(log_path)
    with _APPEND_LOCK:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        seq = _next_seq(log_path)
        fields.pop("seq", None)  # seq is assigned here, never by the caller
        record = {"seq": seq, "at": datetime.now(timezone.utc).isoformat(), "event": event_type, **fields}
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        _LINE_COUNTS[str(log_path)] = (log_path.stat().st_size, seq + 1)
    return record


def read_events(log_path: Path = DEFAULT_LOG_PATH) -> list[dict]:
    if not log_path.exists():
        return []
    events = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def read_events_with_seq(log_path: Path = DEFAULT_LOG_PATH) -> list[dict]:
    """All events, oldest first, each with an integer `seq`. Legacy lines written before
    `seq` existed get their 0-based line index -- computed here, never written back."""
    if not log_path.exists():
        return []
    events = []
    index = 0
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            index += 1  # a malformed line still occupies its index
            continue
        if isinstance(event, dict):
            if not isinstance(event.get("seq"), int) or isinstance(event.get("seq"), bool):
                event["seq"] = index
                event["seq_source"] = "line_index"
            events.append(event)
        index += 1
    return events


def read_recent_traversals(limit: int = 10, log_path: Path = DEFAULT_LOG_PATH) -> list[dict]:
    """The most recent accept-and-follow (Q traversal) events, oldest of the selected
    window first, capped at `limit`. This is what a session review reads."""
    traversals = [e for e in read_events(log_path) if e.get("event") == TRAVERSAL_EVENT]
    return traversals[-limit:]


def last_encounter(log_path: Path = DEFAULT_LOG_PATH, field: str | None = None) -> dict | None:
    """The most recent `page_viewed` or `back` event (optionally within one field): the
    server's own record of which page the reader is looking at."""
    for event in reversed(read_events(log_path)):
        if event.get("event") not in ("page_viewed", "back"):
            continue
        if field is not None and event.get("field") not in (None, field):
            continue
        return event
    return None
