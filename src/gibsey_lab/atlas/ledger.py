"""Hard budget ledger for live provider attempts. Implements `scoring.BudgetLedger`.

Append-only JSONL, one line per event: `reserve` | `settle` | `release` | `refuse`
(`refuse` is informational and never counts). One reservation = one HTTP attempt, so
retries are counted like any other attempt.

Guarantees:
- The caps are module constants. A `Ledger` may be constructed with *stricter* limits,
  never looser ones.
- Totals are recomputed from the file -- at construction and again, incrementally, under
  an exclusive file lock before every reservation -- so a restart, a resume, or a second
  process sharing the file can never reset or double the allowance.
- A reservation with no settle/release line (a process died mid-request, or another
  process is mid-request) counts as one spent attempt at its estimated tokens.
- In-flight is counted from the FILE, under the file lock: every unsettled reservation
  younger than IN_FLIGHT_STALE_SECONDS, whoever made it, so several Ledger instances or
  processes on one file share one MAX_IN_FLIGHT. An older unsettled reservation is
  treated as dead: it stays charged as spent but no longer blocks new attempts. (The
  window is far above the 30 s request timeout, so a live request is never mistaken
  for a dead one.)
- The file is self-healing: before every append, if the last byte is not a newline (a
  torn write), a newline is written first, so a torn fragment can never swallow the next
  line. The fragment itself is then an unreadable line and is charged as one attempt.
- `settle` / `release` never raise for an id this ledger cannot find (the HTTP attempt
  has already happened by then): the line is still appended, flagged
  `unknown_reservation: true`, and counted as an attempt of its own -- over-counting is
  the safe direction.
- On settle, tokens are reconciled to `usage["input_tokens"]` when the provider reported
  it. With no usable usage (every failed attempt, or a response without usage) the
  estimate is charged and the settle line is flagged `usage_unknown: true`.
- `reserve` never blocks: above MAX_IN_FLIGHT it simply refuses (the build's own worker
  pool already bounds concurrency).
- Thread-safe. Only the lead runs this against `data/atlas/ledger.jsonl`; the mock
  dispatch never touches a ledger.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:  # POSIX only; without it the ledger is still correct within one process
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

REPO_ROOT = Path(__file__).resolve().parents[3]
LEDGER_PATH = REPO_ROOT / "data" / "atlas" / "ledger.jsonl"

SCHEMA = "atlas-ledger/1"
MAX_ATTEMPTS = 2000
MAX_INPUT_TOKENS = 10_000_000
MAX_IN_FLIGHT = 2
IN_FLIGHT_STALE_SECONDS = 180  # an unsettled reservation older than this is dead: spent, but not blocking

_AT_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _utcnow().strftime(_AT_FORMAT)


def _parse_at(value) -> datetime | None:
    try:
        return datetime.strptime(value, _AT_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _reported_input_tokens(usage: dict | None) -> int | None:
    if not isinstance(usage, dict):
        return None
    value = usage.get("input_tokens")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return int(value)


class Ledger:
    def __init__(
        self, path: Path | None = None, *, max_attempts: int = MAX_ATTEMPTS,
        max_input_tokens: int = MAX_INPUT_TOKENS, max_in_flight: int = MAX_IN_FLIGHT,
    ) -> None:
        self.path = Path(path) if path is not None else Path(LEDGER_PATH)
        self.max_attempts = min(int(max_attempts), MAX_ATTEMPTS)
        self.max_input_tokens = min(int(max_input_tokens), MAX_INPUT_TOKENS)
        self.max_in_flight = min(int(max_in_flight), MAX_IN_FLIGHT)
        self._lock = threading.Lock()
        self._offset = 0
        self._reservations: dict[str, dict] = {}  # id -> {"est": int, "state": open|settled|released, ...}
        self._corrupt_lines = 0
        with self._lock:
            self._refresh()

    # ------------------------------------------------------------------ file handling

    @contextmanager
    def _exclusive(self):
        """Exclusive cross-process lock on the ledger file, held for read+check+append."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a+", encoding="utf-8") as f:
            if fcntl is not None:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                yield f
            finally:
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _refresh(self) -> None:
        """Fold any lines appended since the last look (by anyone) into the totals."""
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return
        if size < self._offset:  # the file was replaced: trust nothing cached
            self._offset = 0
            self._reservations = {}
            self._corrupt_lines = 0
        if size == self._offset:
            return
        with open(self.path, "rb") as f:
            f.seek(self._offset)
            chunk = f.read()
        end = chunk.rfind(b"\n") + 1
        for raw in chunk[:end].split(b"\n"):
            if raw.strip():
                self._apply(raw)
        self._offset += end

    def _apply(self, raw: bytes) -> None:
        try:
            line = json.loads(raw.decode("utf-8"))
            event = line["event"]
            rid = line.get("reservation_id")
        except (ValueError, UnicodeDecodeError, KeyError, TypeError):
            # Unreadable history is charged as one attempt rather than forgiven.
            self._corrupt_lines += 1
            return
        if event == "reserve" and rid:
            self._reservations.setdefault(rid, {
                "est": int(line.get("est_input_tokens") or 0), "state": "open", "ok": None,
                "tokens": None, "usage_unknown": False, "returned_model": None, "kind": line.get("kind"),
                "at": _parse_at(line.get("at")),
            })
        elif event == "settle" and rid:
            if rid not in self._reservations:
                # Its reserve line was lost or unreadable. The attempt happened: count it.
                self._reservations[rid] = {"est": 0, "state": "open", "ok": None, "tokens": None,
                                           "usage_unknown": False, "returned_model": None, "kind": None, "at": None}
            r = self._reservations[rid]
            if r["state"] != "open":
                return  # the first settlement stands
            r["state"] = "settled"
            r["ok"] = bool(line.get("ok"))
            r["usage_unknown"] = bool(line.get("usage_unknown"))
            r["tokens"] = int(line.get("charged_input_tokens") if line.get("charged_input_tokens") is not None else r["est"])
            r["returned_model"] = line.get("returned_model")
        elif event == "release" and rid in self._reservations:
            if self._reservations[rid]["state"] == "open":
                self._reservations[rid]["state"] = "released"

    def _append(self, f, line: dict) -> None:
        size = os.fstat(f.fileno()).st_size
        if size:
            with open(self.path, "rb") as tail:
                tail.seek(size - 1)
                if tail.read(1) != b"\n":
                    f.write("\n")  # heal a torn trailing line so it cannot swallow this one
        f.write(json.dumps({"schema": SCHEMA, "at": _now(), "pid": os.getpid(), **line}, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())

    # ------------------------------------------------------------------ totals

    def _in_flight(self) -> int:
        """Unsettled reservations in the file, by anyone, young enough to still be running."""
        now = _utcnow()
        return sum(
            1 for r in self._reservations.values()
            if r["state"] == "open" and r["at"] is not None
            and (now - r["at"]).total_seconds() < IN_FLIGHT_STALE_SECONDS
        )

    def _totals(self) -> dict:
        counted = [r for r in self._reservations.values() if r["state"] != "released"]
        settled = [r for r in counted if r["state"] == "settled"]
        unsettled = [r for r in counted if r["state"] == "open"]
        tokens_reported = sum(r["tokens"] for r in settled if not r["usage_unknown"])
        tokens_unknown = sum(r["tokens"] for r in settled if r["usage_unknown"])
        tokens_unsettled = sum(r["est"] for r in unsettled)
        return {
            "attempts": len(counted) + self._corrupt_lines,
            "settled_ok": sum(1 for r in settled if r["ok"]),
            "settled_failed": sum(1 for r in settled if not r["ok"]),
            "unsettled": len(unsettled),
            "in_flight": self._in_flight(),
            "tokens_reported": tokens_reported,
            "tokens_estimated_unknown": tokens_unknown,
            "tokens_unsettled_estimate": tokens_unsettled,
            "tokens_total": tokens_reported + tokens_unknown + tokens_unsettled,
        }

    # ------------------------------------------------------------------ BudgetLedger

    def reserve(self, *, request_sha256: str, kind: str, est_input_tokens: int) -> str | None:
        """Returns a reservation id, or None if any cap would be exceeded. Never blocks."""
        est = max(0, int(est_input_tokens))
        with self._lock, self._exclusive() as f:
            self._refresh()
            totals = self._totals()
            reason = None
            if totals["in_flight"] >= self.max_in_flight:
                reason = f"in-flight cap: {totals['in_flight']} of {self.max_in_flight} already in flight"
            elif totals["attempts"] + 1 > self.max_attempts:
                reason = f"attempt cap: {totals['attempts']} of {self.max_attempts} already used"
            elif totals["tokens_total"] + est > self.max_input_tokens:
                reason = f"token cap: {totals['tokens_total']} used + {est} estimated > {self.max_input_tokens}"
            if reason is not None:
                self._append(f, {"event": "refuse", "request_sha256": request_sha256, "kind": kind,
                                 "est_input_tokens": est, "reason": reason})
                self._refresh()
                return None
            rid = f"res-{uuid.uuid4().hex}"
            self._append(f, {"event": "reserve", "reservation_id": rid, "request_sha256": request_sha256,
                             "kind": kind, "est_input_tokens": est})
            self._refresh()
            return rid

    def settle(
        self, reservation_id: str, *, ok: bool, usage: dict | None, returned_model: str | None, error: str | None
    ) -> None:
        with self._lock, self._exclusive() as f:
            self._refresh()
            reservation = self._reservations.get(reservation_id)
            if reservation is not None and reservation["state"] != "open":
                return  # already settled/released; never charge twice
            # An id we cannot find must still be settled, never raise: the HTTP attempt is done.
            est = reservation["est"] if reservation is not None else 0
            reported = _reported_input_tokens(usage)
            line = {
                "event": "settle", "reservation_id": reservation_id, "ok": bool(ok),
                "usage": usage if isinstance(usage, dict) else None,
                "est_input_tokens": est,
                "charged_input_tokens": reported if reported is not None else est,
                "usage_unknown": reported is None,
                "returned_model": returned_model,
                "error": error,
            }
            if reservation is None:
                line["unknown_reservation"] = True
            self._append(f, line)
            self._refresh()

    def release(self, reservation_id: str) -> None:
        """For a reservation whose HTTP attempt was provably never sent. Frees its
        capacity; an attempt that may have reached the provider must be settled instead."""
        with self._lock, self._exclusive() as f:
            self._refresh()
            reservation = self._reservations.get(reservation_id)
            if reservation is not None and reservation["state"] != "open":
                return
            line = {"event": "release", "reservation_id": reservation_id}
            if reservation is None:
                line["unknown_reservation"] = True  # nothing to free; recorded, never raised
            self._append(f, line)
            self._refresh()

    # ------------------------------------------------------------------ reporting

    def summary(self) -> dict:
        with self._lock:
            self._refresh()
            totals = self._totals()
            models = sorted({r["returned_model"] for r in self._reservations.values() if r["returned_model"]})
        return {
            **totals,
            "corrupt_lines_charged_as_attempts": self._corrupt_lines,
            "remaining_attempts": max(0, self.max_attempts - totals["attempts"]),
            "remaining_input_tokens": max(0, self.max_input_tokens - totals["tokens_total"]),
            "returned_models": models,
            "caps": {"max_attempts": self.max_attempts, "max_input_tokens": self.max_input_tokens,
                     "max_in_flight": self.max_in_flight},
            "path": str(self.path),
        }
