"""Core: validate reader actions, deduplicate requests, commit atomically, then project.

    resolve_options(session_id, operator, policy)      -> persisted offer set at revision r
    execute_action(session_id, offer_set_id, bond_version_id, expected_revision, request_id)
    resume_session(session_id)                          -> state + ordered encounters
    get_action_status(session_id, request_id)           -> committed | rejected | unknown

Order of checks in execute_action (plan §6): (1) request deduplication -- an identical
retry returns the recorded result, the same request_id with different inputs is rejected
as `request_id_reused`; only then (2) session/ownership/revision/membership/source/
eligibility validation; then (3) ONE atomic journal append commits the transition, the
resulting state and the completion event together; then (4) projections, which are
derived and rebuildable. A rejection is also journaled (`action_rejected`) so a retried
rejected request returns its recorded refusal instead of being re-evaluated.

No provider is called anywhere here. Offers are built from the frozen atlas through an
injected `options_provider` (default: memory.operator_options.operator_options).
"""
from __future__ import annotations

import re
import secrets
from pathlib import Path
from typing import Callable

from ..fields import DEFAULT_POLICY, Field, load_field
from . import identity, journal, reducer

OPERATORS = identity.OPERATORS
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
WORDING_SOURCE = "destination_opening_sentence"  # mechanical; see `bond_wording`


class CoreError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 409, details: dict | None = None):
        super().__init__(message)
        self.code, self.status, self.details = code, status, details or {}


def bond_wording(destination_text: str) -> str:
    """The exact offered sentence for a bond. This session has NO authored bond wording,
    so the offer quotes the destination's opening sentence verbatim (exact recorded
    prose, not generated). Recorded as `wording_source` on every bond so an authored
    wording can replace it as a new bond version later (an artistic decision)."""
    text = " ".join(destination_text.split())
    m = re.match(r"(.+?[.!?…]['\"”’)]*)(\s|$)", text)
    return (m.group(1) if m else text[:200]).strip()


class Core:
    def __init__(self, *, core_dir: Path = journal.DEFAULT_CORE_DIR, field: Field | None = None,
                 options_provider: Callable | None = None, projectors: list[Callable] | None = None):
        self.core_dir = core_dir
        self._field = field
        self._options_provider = options_provider
        self.projectors = list(projectors or [])  # called with (session_id, event, state) AFTER commit

    # ------------------------------------------------------------------ helpers

    @property
    def field(self) -> Field:
        if self._field is None:
            self._field = load_field("full-41")
        return self._field

    def _options(self, page_id: str, operator: str, policy: str) -> dict:
        if self._options_provider is None:
            from ..memory.operator_options import operator_options
            self._options_provider = lambda f, p, o, policy: operator_options(f, p, o, policy=policy, mode="live")
        return self._options_provider(self.field, page_id, operator, policy)

    def _version(self, page_id: str) -> str:
        page = self.field.manifest.get(page_id)
        if page is None:
            raise CoreError("unknown_page", f"{page_id!r} is not in field {self.field.id!r}", status=404)
        return identity.version_id(page_id, page.sha256)

    def state(self, session_id: str) -> reducer.State:
        if not SESSION_ID_RE.match(session_id or ""):
            raise CoreError("invalid_session", f"invalid session id {session_id!r}", status=400)
        events = journal.read_events(session_id, self.core_dir)
        if not events:
            raise CoreError("unknown_session", f"no such session: {session_id}", status=404)
        return reducer.reduce(events)

    def _append(self, session_id: str, state: reducer.State, event_type: str, payload: dict, *, bumps: bool) -> dict:
        return journal.append(session_id, event_type, payload, revision_after=state.r + (1 if bumps else 0),
                              core_dir=self.core_dir, expected_seq=state.last_seq + 1)

    def _project(self, session_id: str, event: dict) -> list[str]:
        """Run projectors after a commit. A projector failure is reported, never raised:
        the journal is authoritative and mirrors can be rebuilt from it."""
        state = self.state(session_id)
        errors = []
        for projector in self.projectors:
            try:
                projector(session_id, event, state)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{type(e).__name__}: {e}")
        return errors

    # ------------------------------------------------------------------ API

    def start_session(self, page_id: str, *, session_id: str | None = None, via: str = "start") -> dict:
        session_id = session_id or f"s_{secrets.token_hex(6)}"
        if not SESSION_ID_RE.match(session_id):
            raise CoreError("invalid_session", f"invalid session id {session_id!r}", status=400)
        if journal.read_events(session_id, self.core_dir):
            raise CoreError("session_exists", f"session {session_id} already exists")
        vid = self._version(page_id)
        event = journal.append(session_id, "session_started", {
            "field_id": self.field.id, "version_id": vid, "page_id": page_id,
            "sha256": self.field.manifest[page_id].sha256, "via": via,
        }, revision_after=1, core_dir=self.core_dir, expected_seq=0)
        self._project(session_id, event)
        return self.resume_session(session_id)

    def resume_session(self, session_id: str) -> dict:
        state = self.state(session_id)
        return {"session_id": session_id, "state": state.canonical(), "revision": state.r, "active_version": state.v,
                "active_page": state.page, "paused": state.paused, "encounters": state.H,
                "offer_sets_at_revision": sorted(state.offer_sets)}

    def resolve_options(self, session_id: str, operator: str, *, policy: str = DEFAULT_POLICY) -> dict:
        """Persist the ordered bonds available at the session's current revision. Repeating
        the call at the same revision returns the same offer set without a new event."""
        if operator not in OPERATORS:
            raise CoreError("unknown_operator", f"unknown operator {operator!r}", status=400)
        state = self.state(session_id)
        if state.paused:
            raise CoreError("paused", "the session is paused; resume before resolving options")
        source_version = state.v
        source_page = state.page
        if self._version(source_page) != source_version:
            raise CoreError("source_version_changed",
                            f"the active version {source_version} is no longer the current text of {source_page}")
        options = self._options(source_page, operator, policy)
        bonds = []
        for option in options.get("options") or []:
            dest = option["destination_id"]
            dest_text = self.field.manifest[dest].text
            dest_version = self._version(dest)
            if dest_version != identity.version_id(dest, option.get("destination_sha256") or self.field.manifest[dest].sha256):
                continue  # the atlas row cites a different version of the destination: not offerable
            wording = bond_wording(dest_text)
            fit = option.get("operator_fit") or {}
            bonds.append({
                "bond_version_id": identity.bond_version_id(source_version=source_version, destination_version=dest_version,
                                                            operator=operator, wording=wording),
                "source_version": source_version, "destination_version": dest_version, "destination_page": dest,
                "operator": operator, "wording": wording, "wording_source": WORDING_SOURCE,
                "tier": option.get("tier"), "tier_label": option.get("tier_label"),
                "operator_fit": {k: fit.get(k) for k in ("dimension", "score", "score_norm", "confidence", "nearest_level")},
                "cautions": list(option.get("cautions") or []),
                "assessment_id": option.get("assessment_id"),
                "rank": option.get("rank"), "rank_reasons": option.get("rank_reasons"),
            })
        offer_set_id = identity.offer_set_id(
            session_id=session_id, revision=state.r, source_version=source_version, operator=operator, policy=policy,
            bond_version_ids=[b["bond_version_id"] for b in bonds], options_policy_version=options.get("policy_version", "?"))
        existing = self._find_offer_set(session_id, offer_set_id)
        if existing is not None:
            return {**existing, "reused": True}
        payload = {
            "offer_set_id": offer_set_id, "revision": state.r, "source_version": source_version, "source_page": source_page,
            "operator": operator, "policy": policy, "bond_version_ids": [b["bond_version_id"] for b in bonds],
            "bonds": bonds, "options_policy_version": options.get("policy_version"),
            "options_state": options.get("state"), "counts": options.get("counts"),
            "atlas_config_id": options.get("atlas_config_id"), "unusable": options.get("unusable"),
            "exclusions": {"ineligible_policy": (options.get("counts") or {}).get("ineligible_policy"),
                           "unusable": len(options.get("unusable") or [])},
        }
        event = self._append(session_id, state, "offer_set_created", payload, bumps=False)
        self._project(session_id, event)
        return {**payload, "event_seq": event["seq"], "reused": False}

    def _find_offer_set(self, session_id: str, offer_set_id: str) -> dict | None:
        for event in journal.read_events(session_id, self.core_dir):
            if event.get("event") == "offer_set_created" and event.get("offer_set_id") == offer_set_id:
                return {k: v for k, v in event.items() if k not in ("schema", "at", "session_id", "event", "revision_after")} | {"event_seq": event["seq"]}
        return None

    def get_action_status(self, session_id: str, request_id: str) -> dict:
        state = self.state(session_id)
        if request_id in state.requests:
            return {"status": "committed", "request_id": request_id, **state.requests[request_id]}
        for event in journal.read_events(session_id, self.core_dir):
            if event.get("event") == "action_rejected" and event.get("request_id") == request_id:
                return {"status": "rejected", "request_id": request_id, "code": event.get("code"),
                        "reason": event.get("reason"), "fingerprint": event.get("fingerprint"), "event_seq": event["seq"]}
        return {"status": "unknown", "request_id": request_id}

    def execute_action(self, session_id: str, *, offer_set_id: str, bond_version_id: str,
                       expected_revision: int, request_id: str) -> dict:
        if not request_id or not isinstance(request_id, str):
            raise CoreError("missing_request_id", "an action needs a request_id", status=400)
        state = self.state(session_id)
        fingerprint = identity.request_fingerprint({
            "session_id": session_id, "offer_set_id": offer_set_id, "bond_version_id": bond_version_id,
            "expected_revision": expected_revision,
        })

        # (1) deduplication, before any staleness check
        prior = self.get_action_status(session_id, request_id)
        if prior["status"] == "committed":
            if prior["fingerprint"] != fingerprint:
                raise CoreError("request_id_reused", "this request_id was already used for a different action",
                                details={"recorded": prior})
            return {"status": "committed", "duplicate": True, "request_id": request_id, **prior,
                    "state": state.canonical()}
        if prior["status"] == "rejected":
            if prior["fingerprint"] != fingerprint:
                raise CoreError("request_id_reused", "this request_id was already used for a different action",
                                details={"recorded": prior})
            raise CoreError(prior["code"], prior["reason"], details={"duplicate": True, "recorded": prior})

        # (2) validation
        def reject(code: str, reason: str, **details):
            self._append(session_id, state, "action_rejected",
                         {"request_id": request_id, "fingerprint": fingerprint, "code": code, "reason": reason,
                          "offer_set_id": offer_set_id, "bond_version_id": bond_version_id,
                          "expected_revision": expected_revision, "revision_at_rejection": state.r}, bumps=False)
            raise CoreError(code, reason, details=details)

        if state.paused:
            reject("paused", "the session is paused; navigation is rejected until it is resumed")
        if expected_revision != state.r:
            reject("stale_revision", f"expected revision {expected_revision} but the session is at {state.r}",
                   current_revision=state.r)
        offer_set = state.offer_sets.get(offer_set_id)
        if offer_set is None:
            reject("unknown_or_stale_offer_set",
                   f"offer set {offer_set_id} was not created in this session at revision {state.r}")
        if bond_version_id not in offer_set["bond_version_ids"]:
            reject("not_offered", f"{bond_version_id} is not one of the bonds in {offer_set_id}")
        if offer_set["source_version"] != state.v:
            reject("source_mismatch", f"the offer set starts at {offer_set['source_version']} but the active version is {state.v}")
        full = self._find_offer_set(session_id, offer_set_id)
        bond = next(b for b in full["bonds"] if b["bond_version_id"] == bond_version_id)
        dest_page = bond["destination_page"]
        if self._version(dest_page) != bond["destination_version"]:
            reject("destination_version_changed", f"{dest_page} is no longer the text this bond was made for",
                   bond_destination=bond["destination_version"], current=self._version(dest_page))
        if self._version(state.page) != state.v:
            reject("source_version_changed", f"{state.page} is no longer the text the session is on")
        if dest_page not in self.field.eligible_candidate_ids(state.page, offer_set["policy"]):
            reject("policy_ineligible", f"{dest_page} is not eligible from {state.page} under {offer_set['policy']}")

        # (3) atomic commit: transition + resulting state (revision, encounter) + completion in one event
        event = self._append(session_id, state, "action_committed", {
            "request_id": request_id, "fingerprint": fingerprint, "offer_set_id": offer_set_id,
            "bond_version_id": bond_version_id, "operator": bond["operator"], "wording": bond["wording"],
            "from_version": state.v, "from_page": state.page, "to_version": bond["destination_version"],
            "to_page": dest_page, "expected_revision": expected_revision, "encounter_index": len(state.H),
            "tier": bond.get("tier"), "operator_fit": bond.get("operator_fit"), "assessment_id": bond.get("assessment_id"),
        }, bumps=True)

        # (4) projections (derived; a failure here never un-commits the action)
        projection_errors = self._project(session_id, event)
        new_state = self.state(session_id)
        return {"status": "committed", "duplicate": False, "request_id": request_id, "event_seq": event["seq"],
                "bond_version_id": bond_version_id, "to_version": bond["destination_version"], "to_page": dest_page,
                "revision_after": new_state.r, "encounter_index": len(new_state.H) - 1,
                "state": new_state.canonical(), "projection_errors": projection_errors}

    def pause(self, session_id: str) -> dict:
        state = self.state(session_id)
        if not state.paused:
            self._project(session_id, self._append(session_id, state, "paused", {}, bumps=True))
        return self.resume_session(session_id)

    def unpause(self, session_id: str) -> dict:
        state = self.state(session_id)
        if state.paused:
            self._project(session_id, self._append(session_id, state, "resumed", {}, bumps=True))
        return self.resume_session(session_id)

    def acknowledge_presented(self, session_id: str, offer_set_id: str) -> dict:
        """Reader-render acknowledgement: creation is not presentation. No state change."""
        state = self.state(session_id)
        if offer_set_id not in state.offer_sets:
            raise CoreError("unknown_or_stale_offer_set", f"{offer_set_id} is not current")
        return self._append(session_id, state, "presented", {"offer_set_id": offer_set_id}, bumps=False)
