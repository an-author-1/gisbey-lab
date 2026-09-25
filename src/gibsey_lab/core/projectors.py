"""Projections from the Core journal onto the legacy reader stores.

The journal (`core/journal.py`) is the authority. Everything written here -- `bonds.json`,
`reader_state.json`, the session log's mirror events -- is derived from a committed event
so that the panels, review tools and log readers that predate the Core keep working. A
projector is called by `Core` AFTER the commit; it can be re-run at any time (a repair after
a crash between commit and projection, a rebuild from the journal) and never duplicates:
every store is keyed by `(session_id, core_event_seq)` and skipped when already present.

Nothing here calls a provider, and nothing here is ever read back by the Core.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .. import session_log, state as legacy_state
from ..fields import Field, load_field
from . import identity, reducer

# The session-log mirror of one committed action, in the order the legacy follow path wrote them.
ACTION_MIRROR_EVENTS = ("operator_proposed", "offer_accepted", session_log.TRAVERSAL_EVENT,
                        session_log.Q_TRAVERSAL_EVENT, "page_viewed")
PROPOSAL_KIND = "core_bond"


def _has_mirror(events: list[dict], session_id: str, seq: int, name: str | None = None) -> bool:
    return any(e.get("session_id") == session_id and e.get("core_event_seq") == seq
               and (name is None or e.get("event") == name) for e in events)


def _full_sha256(field: Field | None, page_id: str, version_id: str) -> str | None:
    """The full sha256 behind a version id -- only when the field's current text IS that
    version; a changed page yields None rather than a hash of different bytes."""
    page = field.manifest.get(page_id) if field is not None else None
    if page is None:
        return None
    return page.sha256 if identity.version_id(page_id, page.sha256) == version_id else None


def mirror_to_legacy_stores(data_dir: Path, session_log_path: Path, *, field: Field | None = None) -> Callable:
    """Projector `(session_id, event, state)` mirroring `action_committed` (bond, history
    entry, five session-log events), `relocation_committed` (one `page_viewed` via the
    cause, one history entry, no bond) and `session_started` (one `page_viewed`) onto the
    legacy stores under `data_dir` / `session_log_path`. Idempotent per event seq."""
    data_dir, session_log_path = Path(data_dir), Path(session_log_path)
    fields: dict[str, Field | None] = {}

    def field_for(state) -> Field | None:
        if field is not None:
            return field
        field_id = getattr(state, "field_id", None)
        if field_id not in fields:
            try:
                fields[field_id] = load_field(field_id)
            except Exception:  # noqa: BLE001 -- a mirror without texts is still a mirror
                fields[field_id] = None
        return fields[field_id]

    def project(session_id: str, event: dict, state) -> None:
        kind = event.get("event")
        if kind == "action_committed":
            _mirror_action(session_id, event, state)
        elif kind == "relocation_committed":
            _mirror_relocation(session_id, event, state)
        elif kind == "session_started":
            _mirror_start(session_id, event, state)

    def _mirror_relocation(session_id: str, event: dict, state) -> None:
        """A manual move: ONE `page_viewed` (via = the relocation's cause) and ONE history
        entry `{event: "relocation", ...}` plus the active page. No bond, no proposal, no
        acceptance, no traversal: a relocation asserts no relationship."""
        seq = event["seq"]
        f = field_for(state)
        to_page, to_version = event["to_page"], event["to_version"]
        field_id = getattr(state, "field_id", None)
        destination_sha = _full_sha256(f, to_page, to_version)
        with legacy_state._STATE_LOCK:  # noqa: SLF001
            paths = legacy_state._paths(data_dir)  # noqa: SLF001
            reader = legacy_state._load(paths["reader_state"], {"active_page": None, "active_passage": None, "history": []})  # noqa: SLF001
            history = reader.setdefault("history", [])
            if not _has_mirror(session_log.read_events(session_log_path), session_id, seq, "page_viewed"):
                session_log.append_event(
                    "page_viewed", log_path=session_log_path, field=field_id, page_id=to_page, from_page=event.get("from_page"),
                    via=event.get("cause") or "other", page_sha256=destination_sha, version_id=to_version,
                    from_version=event.get("from_version"), request_id=event.get("request_id"), kind="relocation",
                    session_id=session_id, core_event_seq=seq,
                )
            if any(h.get("session_id") == session_id and h.get("core_event_seq") == seq for h in history):
                return  # already projected (a partial earlier run added the log line above only if it was missing)
            history.append({
                "event": "relocation", "cause": event.get("cause"), "from_page": event.get("from_page"),
                "from_passage": event.get("from_page"), "to_id": to_page, "at": event.get("at"),
                "request_id": event.get("request_id"), "from_version": event.get("from_version"), "to_version": to_version,
                "bond_id": None, "kind": "core", "session_id": session_id, "core_event_seq": seq,
                "encounter_index": event.get("encounter_index"),
            })
            reader["active_page"] = to_page
            reader["active_passage"] = to_page
            legacy_state._save(paths["reader_state"], reader)  # noqa: SLF001

    def _mirror_start(session_id: str, event: dict, state) -> None:
        seq = event["seq"]
        if _has_mirror(session_log.read_events(session_log_path), session_id, seq, "page_viewed"):
            return
        session_log.append_event(
            "page_viewed", log_path=session_log_path, field=event.get("field_id"), page_id=event.get("page_id"),
            from_page=None, via="start", page_sha256=event.get("sha256"), version_id=event.get("version_id"),
            session_id=session_id, core_event_seq=seq, session_via=event.get("via"),
        )

    def _mirror_action(session_id: str, event: dict, state) -> None:
        seq = event["seq"]
        f = field_for(state)
        from_page, to_page = event["from_page"], event["to_page"]
        from_version, to_version = event["from_version"], event["to_version"]
        bond_id = event["bond_version_id"]
        request_id = event.get("request_id")
        operator = event.get("operator")
        field_id = getattr(state, "field_id", None)
        source_sha = _full_sha256(f, from_page, from_version)
        destination_sha = _full_sha256(f, to_page, to_version)
        policy = None
        offer_set = (getattr(state, "offer_sets", None) or {}).get(event.get("offer_set_id"))
        if offer_set:
            policy = offer_set.get("policy")

        with legacy_state._STATE_LOCK:  # noqa: SLF001 -- the same lock the legacy writers take
            paths = legacy_state._paths(data_dir)  # noqa: SLF001
            reader = legacy_state._load(paths["reader_state"], {"active_page": None, "active_passage": None, "history": []})  # noqa: SLF001
            history = reader.setdefault("history", [])
            if any(h.get("session_id") == session_id and h.get("core_event_seq") == seq for h in history):
                return  # already projected: a rebuild or a second run changes nothing

            bonds = legacy_state._load(paths["bonds"], {})  # noqa: SLF001
            if bond_id not in bonds:
                target = f.manifest.get(to_page) if f is not None else None
                bonds[bond_id] = {
                    "bond_id": bond_id, "proposal_id": None, "kind": "core",
                    "source_id": from_page, "active_id": None, "target_id": to_page,
                    "target_text": target.text if target is not None and destination_sha else None,
                    "field": field_id, "policy": policy, "operator": operator, "relation_labels": None,
                    "run_dir": None, "offer_set_id": event.get("offer_set_id"),
                    "tier": event.get("tier"), "operator_fit": event.get("operator_fit"),
                    "source_version": from_version, "destination_version": to_version,
                    "source_sha256": source_sha, "destination_sha256": destination_sha,
                    "wording": event.get("wording"), "request_id": request_id,
                    "session_id": session_id, "core_event_seq": seq, "assessment_id": event.get("assessment_id"),
                    "created_at": event.get("at"),
                }
                legacy_state._save(paths["bonds"], bonds)  # noqa: SLF001

            existing = session_log.read_events(session_log_path)
            common = dict(
                log_path=session_log_path, field=field_id, source=from_page, destination=to_page, operator=operator,
                policy=policy, proposal_kind=PROPOSAL_KIND, run_dir=None, offer_set_id=event.get("offer_set_id"),
                proposal_id=None, request_id=request_id, session_id=session_id, core_event_seq=seq,
                bond_version_id=bond_id, version_id=to_version, source_version=from_version, tier=event.get("tier"),
                operator_fit=event.get("operator_fit"),
            )
            for name in ACTION_MIRROR_EVENTS:
                if _has_mirror(existing, session_id, seq, name):
                    continue  # a partial earlier run: only the missing lines are added
                if name == "operator_proposed":
                    session_log.append_event(name, page_sha256=source_sha, destination_sha256=destination_sha, **common)
                elif name == "offer_accepted":
                    session_log.append_event(name, bond_id=bond_id, page_sha256=source_sha, **common)
                elif name == session_log.TRAVERSAL_EVENT:
                    session_log.append_event(name, bond_id=bond_id, page_sha256=source_sha, **common)
                elif name == session_log.Q_TRAVERSAL_EVENT:
                    session_log.append_event(name, bond_id=bond_id, from_page=from_page, page_sha256=source_sha,
                                             destination_sha256=destination_sha, **common)
                else:
                    session_log.append_event(
                        "page_viewed", log_path=session_log_path, field=field_id, page_id=to_page, from_page=from_page,
                        via="traversal", page_sha256=destination_sha, policy=policy, operator=operator, bond_id=bond_id,
                        bond_version_id=bond_id, request_id=request_id, proposal_kind=PROPOSAL_KIND,
                        session_id=session_id, core_event_seq=seq, version_id=to_version, tier=event.get("tier"),
                        operator_fit=event.get("operator_fit"),
                    )

            history.append({
                "event": "Q_follow", "bond_id": bond_id, "from_page": from_page, "from_passage": from_page,
                "to_id": to_page, "at": event.get("at"), "follow_token": request_id,
                "from_version": from_version, "to_version": to_version, "kind": "core",
                "session_id": session_id, "core_event_seq": seq, "encounter_index": event.get("encounter_index"),
            })
            reader["active_page"] = to_page
            reader["active_passage"] = to_page
            legacy_state._save(paths["reader_state"], reader)  # noqa: SLF001

    return project


def rebuild(session_id: str, events: list[dict], projector: Callable) -> int:
    """Re-run `projector` over a session's committed events in order (each with the state
    after it): the repair after a crash between commit and projection. Returns the number
    of events offered. Idempotent because every mirror is keyed by event seq."""
    state, offered = reducer.State(), 0
    for event in events:
        state = reducer.apply(state, event)
        projector(session_id, event, state)
        offered += 1
    return offered
