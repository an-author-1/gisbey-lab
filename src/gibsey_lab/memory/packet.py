"""The reader memory packet: what this reader has actually encountered, in order.

Built only from session-log events plus the corpus manifest -- never from client state.

Guarantees:
- An encounter is a `page_viewed` or `back` event. A Back is a NEW encounter of the page
  returned to (`arrived_via="back"`, `revisit=True`); no earlier encounter is ever removed
  or rewritten. Consecutive duplicate views of the same page collapse into the first.
- Legacy events (no `seq`, no `page_sha256`) are accepted: `seq` falls back to the event's
  index in the log and `version_source` is "current_manifest". If an event carries a
  `page_sha256` that differs from the current manifest, the encounter is kept but marked
  `text_available=False, version_source="event_hash_mismatch"` -- the current text is
  never supplied as if it were what was read.
- `model_visible_state(packet)` is EXACTLY the history sent to the provider: ordered texts,
  neutral arrival labels, the omitted-encounter count, and the reader's own stated
  intention verbatim if one was supplied. It contains no page ids, no hashes, no human
  notes, no reviewer or agent text, and no inference that visiting a page means liking,
  agreeing with, or endorsing anything. `memory_sha256` hashes that state and nothing else.
- Arrival labels say what actually happened. Following the destination an OPERATOR
  request selected (a Choice selection; legacy `accept_and_follow`, or a traversal with
  `proposal_kind="operator"`) is "followed a BRIDGE operator selection". Following a card
  from the route hand (`proposal_kind="offer"`) is "followed an offered route", whatever
  relation labels the card carried.
- A fixture packet is labeled `source: "demonstration_fixture"` and is never written to the
  session log.

Version history: memory-v1 labeled an operator follow "followed a BRIDGE offer". That was
inaccurate -- an operator result is a Choice selection, not an offer from the route hand --
and a single-label hand follow was given the same wording. memory-v2 uses the labels above.
This changes model-visible text, hence the version bump; packets whose arrivals are all
"arrival not specified" (the demonstration fixtures) are textually unchanged, but their
cache keys still change because the policy version is part of the key.
"""
from __future__ import annotations

import hashlib
import json
from typing import Iterable

from ..fields import Field
from ..relational_operators import OPERATOR_NAMES
from ..session_log import DEFAULT_LOG_PATH, TRAVERSAL_EVENT

MEMORY_POLICY_VERSION = "memory-v2"
PACKET_SCHEMA = "memory-packet/1"
WINDOW = 6

ENCOUNTER_EVENTS = ("page_viewed", "back")
TRAVERSAL_EVENTS = (TRAVERSAL_EVENT, "q_traversal")  # legacy accept_and_follow, new q_traversal

SOURCE_SESSION_LOG = "session_log"
SOURCE_FIXTURE = "demonstration_fixture"

# Normalized arrival kinds -> the neutral label the provider sees. A traversal with a
# recorded operator is an operator-selection follow, labeled by _arrival_label instead
# ("followed a DEVELOP operator selection"); "offer" is a follow from the route hand.
ARRIVAL_LABELS = {
    "traversal": "followed an offered route",
    "offer": "followed an offered route",
    "next": "next page",
    "previous": "previous page",
    "prev_next": "next or previous page",
    "back": "back",
    "list": "picked from list",
    "unknown": "arrival not specified",
    "fixture": "arrival not specified",
}

_VIA_ALIASES = {
    "dropdown": "list", "list": "list", "picker": "list",
    "next": "next", "previous": "previous", "prev": "previous", "prev_next": "prev_next",
    "back": "back", "traversal": "traversal",
    "offer": "offer", "follow_offer": "offer", "follow-offer": "offer",
}

NO_HISTORY_NOTE = "No earlier reading history is supplied for this reader."
TEXT_UNAVAILABLE_NOTE = "The text of this page as it was read is not available."


class PacketError(ValueError):
    """Raised for a packet that cannot be built honestly (unknown current page, etc.)."""


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _in_field(event: dict, field: Field) -> bool:
    return event.get("field") in (None, field.id)


def _traversal_before(events: list[dict], index: int, page_id: str, field: Field) -> dict | None:
    """The traversal event immediately preceding the view at `index`: scan back over
    non-encounter events only, stopping at the previous encounter."""
    for j in range(index - 1, -1, -1):
        event = events[j]
        kind = event.get("event")
        if kind in ENCOUNTER_EVENTS and _in_field(event, field):
            return None
        if kind in TRAVERSAL_EVENTS and _in_field(event, field):
            if event.get("destination") in (None, page_id):
                return event
            return None
    return None


def _clean_operator(value) -> str | None:
    if isinstance(value, str) and value.upper() in OPERATOR_NAMES:
        return value.upper()
    return None


def encounters_from_events(events: Iterable[dict], field: Field) -> list[dict]:
    """The full ordered encounter trace (oldest first) for `field`. Nothing is windowed
    here; `build_memory_packet` applies the window."""
    events = list(events)
    encounters: list[dict] = []
    seen: set[str] = set()

    for index, event in enumerate(events):
        kind = event.get("event")
        page_id = event.get("page_id")
        if kind not in ENCOUNTER_EVENTS or not _in_field(event, field) or not isinstance(page_id, str):
            continue
        if encounters and encounters[-1]["page_id"] == page_id:
            continue  # consecutive duplicate view (reload, re-render): one encounter

        traversal = None
        if kind == "back":
            arrived_via = "back"
        else:
            via = event.get("via")
            arrived_via = _VIA_ALIASES.get(via, "unknown") if isinstance(via, str) else "unknown"
            if arrived_via in ("traversal", "unknown"):
                traversal = _traversal_before(events, index, page_id, field)
                if traversal is not None:
                    arrived_via = "traversal"  # legacy views carry no `via` at all
                proposal_kind = (traversal or {}).get("proposal_kind") or event.get("proposal_kind")
                if arrived_via == "traversal" and proposal_kind == "offer":
                    arrived_via = "offer"  # a card from the route hand, not an operator selection
            if arrived_via == "prev_next" and encounters:
                neighbors = field.neighbors_of(encounters[-1]["page_id"]) if encounters[-1]["page_id"] in field.manifest else {}
                if neighbors.get("next") == page_id:
                    arrived_via = "next"
                elif neighbors.get("previous") == page_id:
                    arrived_via = "previous"

        page = field.manifest.get(page_id)
        event_hash = event.get("page_sha256")
        if page is None:
            sha, text, available, version_source = event_hash, None, False, "page_not_in_field"
        elif not event_hash:
            sha, text, available, version_source = page.sha256, page.text, True, "current_manifest"
        elif event_hash == page.sha256:
            sha, text, available, version_source = page.sha256, page.text, True, "event"
        else:
            sha, text, available, version_source = event_hash, None, False, "event_hash_mismatch"

        seq = event.get("seq")
        encounters.append({
            "seq": seq if isinstance(seq, int) and not isinstance(seq, bool) else index,
            "page_id": page_id,
            "sha256": sha,
            "text": text,
            "text_available": available,
            "arrived_via": arrived_via,
            "operator": _clean_operator(traversal.get("operator")) if traversal else None,
            "at": event.get("at"),
            "revisit": kind == "back" or page_id in seen,
            "version_source": version_source,
        })
        seen.add(page_id)
    return encounters


def _assemble(field: Field, current_page_id: str, trace: list[dict], *, candidate_policy: str,
              intention: str | None, source: str, trace_ref: dict) -> dict:
    if current_page_id not in field.manifest:
        raise PacketError(f"current page {current_page_id!r} is not in field {field.id!r}")
    page = field.manifest[current_page_id]

    earlier = list(trace)
    arrival = None
    if earlier and earlier[-1]["page_id"] == current_page_id:
        arrival = earlier.pop()  # the trailing encounter of the current page is the arrival

    window = earlier[-WINDOW:]
    if intention is not None:
        intention = str(intention).strip() or None

    return {
        "schema": PACKET_SCHEMA,
        "policy_version": MEMORY_POLICY_VERSION,
        "source": source,
        "field": field.id,
        "candidate_policy": candidate_policy,
        "current": {
            "page_id": current_page_id,
            "sha256": page.sha256,
            "arrived_via": arrival["arrived_via"] if arrival else ("fixture" if source == SOURCE_FIXTURE else "unknown"),
            "operator": arrival["operator"] if arrival else None,
            "seq": arrival["seq"] if arrival else None,
            "revisit": any(e["page_id"] == current_page_id for e in earlier),
        },
        "window": WINDOW,
        "encounters": window,
        "omitted_earlier_encounters": len(earlier) - len(window),
        "total_earlier_encounters": len(earlier),
        "intention": intention,
        "trace_ref": trace_ref,
    }


def build_memory_packet(field: Field, current_page_id: str, events: Iterable[dict], *, candidate_policy: str,
                        intention: str | None = None, log_path=None) -> dict:
    """The `memory-packet/1` dict for a reader now at `current_page_id`. `encounters` holds
    the WINDOW most recent EARLIER encounters; the complete trace stays in the session log
    (`trace_ref`), and whatever falls outside the window is counted, never hidden."""
    trace = encounters_from_events(events, field)
    trace_ref = {
        "log_path": str(log_path if log_path is not None else DEFAULT_LOG_PATH),
        "first_seq": trace[0]["seq"] if trace else None,
        "last_seq": trace[-1]["seq"] if trace else None,
    }
    return _assemble(field, current_page_id, trace, candidate_policy=candidate_policy, intention=intention,
                     source=SOURCE_SESSION_LOG, trace_ref=trace_ref)


def fixture_packet(field: Field, path_ids: list[str], *, candidate_policy: str, intention: str | None = None) -> dict:
    """A packet from a DECLARED arrival path (last id = current page). A demonstration
    fixture: not the reader's actions, never written to the session log, and every arrival
    is labeled "arrival not specified" because no navigation control was actually used."""
    if not path_ids:
        raise PacketError("a fixture path needs at least the current page")
    unknown = [pid for pid in path_ids if pid not in field.manifest]
    if unknown:
        raise PacketError(f"fixture pages not in field {field.id!r}: {unknown}")
    trace, seen = [], set()
    for index, pid in enumerate(path_ids):
        page = field.manifest[pid]
        trace.append({
            "seq": index, "page_id": pid, "sha256": page.sha256, "text": page.text, "text_available": True,
            "arrived_via": "fixture", "operator": None, "at": None, "revisit": pid in seen,
            "version_source": "current_manifest",
        })
        seen.add(pid)
    trace_ref = {"log_path": None, "first_seq": 0, "last_seq": len(path_ids) - 1, "declared_path": list(path_ids)}
    return _assemble(field, path_ids[-1], trace, candidate_policy=candidate_policy, intention=intention,
                     source=SOURCE_FIXTURE, trace_ref=trace_ref)


def _arrival_label(arrived_via: str, operator: str | None) -> str:
    if arrived_via == "traversal" and operator:
        article = "an" if operator[0] in "AEIOU" else "a"
        return f"followed {article} {operator} operator selection"
    return ARRIVAL_LABELS.get(arrived_via, ARRIVAL_LABELS["unknown"])


def model_visible_state(packet: dict) -> dict:
    """Exactly what the provider is given as reading history -- and nothing else."""
    encounters = []
    for position, encounter in enumerate(packet["encounters"], start=1):
        entry = {
            "order": position,
            "arrived_by": _arrival_label(encounter["arrived_via"], encounter.get("operator")),
            "returning_to_a_page_read_earlier": bool(encounter.get("revisit")),
        }
        if encounter.get("text_available") and encounter.get("text") is not None:
            entry["text"] = encounter["text"]
        else:
            entry["text"] = None
            entry["note"] = TEXT_UNAVAILABLE_NOTE
        encounters.append(entry)

    omitted = int(packet.get("omitted_earlier_encounters") or 0)
    if not encounters and not omitted:
        note = NO_HISTORY_NOTE
    elif omitted:
        note = (f"Encounters are listed oldest first. {omitted} earlier encounter(s) came before these "
                "and are not shown.")
    else:
        note = "Encounters are listed oldest first. This is the complete supplied history."

    current = packet.get("current") or {}
    return {
        "encounters": encounters,
        "omitted_earlier_encounters": omitted,
        "note": note,
        "current_page_arrived_by": _arrival_label(current.get("arrived_via", "unknown"), current.get("operator")),
        "reader_stated_intention": packet.get("intention"),
    }


def memory_sha256(packet: dict) -> str:
    return hashlib.sha256(_canonical(model_visible_state(packet)).encode("utf-8")).hexdigest()


def summarize(packet: dict) -> dict:
    """Compact, text-free view for CLI output and logs (ids are fine here: never sent)."""
    return {
        "schema": packet["schema"],
        "policy_version": packet["policy_version"],
        "source": packet["source"],
        "field": packet["field"],
        "candidate_policy": packet["candidate_policy"],
        "current": packet["current"],
        "window": packet["window"],
        "encounters": [
            {k: e[k] for k in ("seq", "page_id", "arrived_via", "operator", "revisit", "version_source", "text_available")}
            for e in packet["encounters"]
        ],
        "omitted_earlier_encounters": packet["omitted_earlier_encounters"],
        "intention": packet["intention"],
        "trace_ref": packet["trace_ref"],
        "memory_sha256": memory_sha256(packet),
    }
