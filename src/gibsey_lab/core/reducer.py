"""Pure state reduction (v0.3 plan §4.3, §4.4): S_{t+1} = reduce(S_t, e_t).

No I/O, no clock, no provider. The same function serves the runtime, the replay check
and a future simulator, which is the point of keeping it here.

State S_t = (v, z, H, c, ell, u, r):
    v    active exact content version (version_id) and its page
    z    score identity/movement -- fixed to the neutral placeholder this session
    H    ordered encounters: one entry per committed arrival; a return is another entry
    c    encounter counts per exact version
    ell  last encounter index per exact version (index into H)
    u    open threads: not used yet (empty)
    r    state revision: increments on every state-changing event
    plus: paused flag, last committed request ids -> results (for deduplication),
          the offer sets created at the current revision, and encounter_seq (arrival
          order, separate from event seq).

Which events change state (and so bump r): session_started, action_committed (which
carries the arrival), paused, resumed. Which do not: offer_set_created, presented,
action_rejected. Refresh, replay and retries add no events at all, so they cannot add
encounters.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

NEUTRAL_SCORE = {"score_id": "neutral", "score_version": 1, "movement": "open"}


@dataclass
class State:
    session_id: str | None = None
    v: str | None = None                  # active version id
    page: str | None = None               # logical page of v
    z: dict = field(default_factory=lambda: dict(NEUTRAL_SCORE))
    H: list[dict] = field(default_factory=list)      # ordered encounters
    c: dict[str, int] = field(default_factory=dict)  # encounter counts per version
    ell: dict[str, int] = field(default_factory=dict)  # last encounter index per version
    u: list = field(default_factory=list)
    r: int = 0
    paused: bool = False
    field_id: str | None = None
    requests: dict[str, dict] = field(default_factory=dict)   # request_id -> committed result summary
    offer_sets: dict[str, dict] = field(default_factory=dict)  # offer_set_id -> {revision, source_version, ...}
    last_seq: int = -1

    @property
    def encounter_seq(self) -> int:
        return len(self.H)

    def canonical(self) -> dict:
        """Comparable form for replay checks; excludes nothing that affects behaviour."""
        return {
            "session_id": self.session_id, "v": self.v, "page": self.page, "z": self.z, "H": self.H, "c": self.c,
            "ell": self.ell, "u": self.u, "r": self.r, "paused": self.paused, "field_id": self.field_id,
            "requests": self.requests, "offer_sets": self.offer_sets, "last_seq": self.last_seq,
        }


class ReduceError(Exception):
    pass


def _arrive(state: State, *, version_id: str, page_id: str, via: str, event_seq: int,
            bond_version_id: str | None, from_version: str | None, request_id: str | None) -> None:
    index = len(state.H)
    entry = {
        "encounter_index": index, "version_id": version_id, "page_id": page_id, "via": via,
        "event_seq": event_seq, "from_version": from_version, "bond_version_id": bond_version_id,
        "request_id": request_id,
        "previous_encounter_index": state.ell.get(version_id),
    }
    if entry["previous_encounter_index"] is not None:
        k = entry["previous_encounter_index"]
        entry["return_index_distance"] = index - k          # plan §4.5: t - k
        entry["intervening_encounters"] = index - k - 1     # t - k - 1
    state.H.append(entry)
    state.c[version_id] = state.c.get(version_id, 0) + 1
    state.ell[version_id] = index
    state.v = version_id
    state.page = page_id


def apply(state: State, event: dict) -> State:
    """Return a NEW state with `event` applied. Raises on an event that cannot follow."""
    s = copy.deepcopy(state)
    kind = event.get("event")
    seq = event.get("seq")
    if seq != s.last_seq + 1:
        raise ReduceError(f"event seq {seq} does not follow {s.last_seq}")
    s.last_seq = seq

    if kind == "session_started":
        if s.v is not None:
            raise ReduceError("session already started")
        s.session_id = event["session_id"]
        s.field_id = event.get("field_id")
        s.r += 1
        _arrive(s, version_id=event["version_id"], page_id=event["page_id"], via=event.get("via", "start"),
                event_seq=seq, bond_version_id=None, from_version=None, request_id=None)
    elif kind == "offer_set_created":
        s.offer_sets[event["offer_set_id"]] = {
            "revision": event["revision"], "source_version": event["source_version"], "operator": event.get("operator"),
            "policy": event.get("policy"), "bond_version_ids": list(event.get("bond_version_ids") or []),
        }
    elif kind == "action_committed":
        if s.v is None:
            raise ReduceError("no active version")
        if s.paused:
            raise ReduceError("session is paused")
        if event["from_version"] != s.v:
            raise ReduceError(f"action from {event['from_version']} but active version is {s.v}")
        s.r += 1
        _arrive(s, version_id=event["to_version"], page_id=event["to_page"], via="Q",
                event_seq=seq, bond_version_id=event["bond_version_id"], from_version=event["from_version"],
                request_id=event.get("request_id"))
        s.requests[event["request_id"]] = {
            "fingerprint": event["fingerprint"], "event_seq": seq, "bond_version_id": event["bond_version_id"],
            "to_version": event["to_version"], "to_page": event["to_page"], "revision_after": s.r,
            "encounter_index": len(s.H) - 1,
        }
        s.offer_sets = {k: v for k, v in s.offer_sets.items() if v["revision"] == s.r}  # earlier offers are stale
    elif kind == "action_rejected":
        pass  # recorded, never applied
    elif kind == "paused":
        s.paused = True
        s.r += 1
    elif kind == "resumed":
        s.paused = False
        s.r += 1
    elif kind == "presented":
        pass
    else:
        raise ReduceError(f"unknown event: {kind!r}")

    declared = event.get("revision_after")
    if declared is not None and declared != s.r:
        raise ReduceError(f"event {seq} declares revision_after={declared} but reduction gives {s.r}")
    return s


def reduce(events: list[dict], initial: State | None = None) -> State:
    state = initial if initial is not None else State()
    for event in events:
        state = apply(state, event)
    return state


def reduce_with_trace(events: list[dict]) -> list[dict]:
    """Canonical state after every event -- the 'state replay' check of plan §7."""
    state, trace = State(), []
    for event in events:
        state = apply(state, event)
        trace.append({"seq": event["seq"], "event": event["event"], "state": state.canonical()})
    return trace
