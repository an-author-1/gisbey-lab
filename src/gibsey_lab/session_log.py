"""Automatic, passive session-route log: which pages were viewed, which field/operator
was active, which run records were shown or used, and Q traversal/backtracking.

Requires no written notes -- every event here is appended automatically by the reader
app as a side effect of normal navigation and Jev requests. Never preserves anything into
the Gibsey Vault on its own (that stays a separate, explicit action via state.preserve).
Kept out of Jev's input entirely: nothing in this module is ever read by jev_client or
mock_client, and no reader/session-log code path constructs a Choice request.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .corpus import REPO_ROOT

DEFAULT_LOG_PATH = REPO_ROOT / "data" / "session_log.jsonl"

TRAVERSAL_EVENT = "accept_and_follow"


def append_event(event_type: str, log_path: Path = DEFAULT_LOG_PATH, **fields) -> dict:
    record = {"at": datetime.now(timezone.utc).isoformat(), "event": event_type, **fields}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
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


def read_recent_traversals(limit: int = 10, log_path: Path = DEFAULT_LOG_PATH) -> list[dict]:
    """The most recent accept-and-follow (Q traversal) events, oldest of the selected
    window first, capped at `limit`. This is what a session review reads."""
    traversals = [e for e in read_events(log_path) if e.get("event") == TRAVERSAL_EVENT]
    return traversals[-limit:]
