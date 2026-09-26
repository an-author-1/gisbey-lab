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
from . import identity, journal, reducer, resolver, scores

OPERATORS = identity.OPERATORS
RELOCATION_CAUSES = ("previous", "next", "page_list", "back", "history_back", "history_forward", "resume_here", "other")
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
                 options_provider: Callable | None = None, projectors: list[Callable] | None = None,
                 candidate_provider: Callable | None = None):
        self.core_dir = core_dir
        self._field = field
        self._options_provider = options_provider
        self._candidate_provider = candidate_provider
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
            return operator_options(self.field, page_id, operator, policy=policy, mode="live")
        return self._options_provider(self.field, page_id, operator, policy)

    def _version(self, page_id: str) -> str:
        page = self.field.manifest.get(page_id)
        if page is None:
            raise CoreError("unknown_page", f"{page_id!r} is not in field {self.field.id!r}", status=404)
        return identity.version_id(page_id, page.sha256)

    def _retain_new_versions(self, session_id: str, page_ids: list[str]) -> dict:
        retained = {version for event in journal.read_events(session_id, self.core_dir)
                    for version in event.get("retained_content", {})}
        return {self._version(page_id): {"page_id": page_id, "text": self.field.manifest[page_id].text,
                                         "sha256": self.field.manifest[page_id].sha256, "retained": True}
                for page_id in page_ids if self._version(page_id) not in retained}

    def state(self, session_id: str) -> reducer.State:
        if not SESSION_ID_RE.match(session_id or ""):
            raise CoreError("invalid_session", f"invalid session id {session_id!r}", status=400)
        events = journal.read_events(session_id, self.core_dir)
        if not events:
            raise CoreError("unknown_session", f"no such session: {session_id}", status=404)
        return reducer.reduce(events)

    def _append(self, session_id: str, state: reducer.State, event_type: str, payload: dict, *, bumps: bool) -> dict:
        if "config" in state.z:
            projected = reducer.apply(state, {**payload, "seq": state.last_seq + 1, "event": event_type,
                                             "revision_after": state.r + int(bumps)})
            payload = {**payload, "score_after": projected.z}
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

    def start_session(self, page_id: str, *, session_id: str | None = None, via: str = "start",
                      score_config: dict | None = None) -> dict:
        session_id = session_id or f"s_{secrets.token_hex(6)}"
        if not SESSION_ID_RE.match(session_id):
            raise CoreError("invalid_session", f"invalid session id {session_id!r}", status=400)
        if journal.read_events(session_id, self.core_dir):
            raise CoreError("session_exists", f"session {session_id} already exists")
        vid = self._version(page_id)
        try:
            score_state = scores.initial(score_config if score_config is not None else scores.neutral_score(), vid)
        except scores.ScoreError as error:
            raise CoreError("invalid_score", str(error), status=400) from error
        event = journal.append(session_id, "session_started", {
            "field_id": self.field.id, "version_id": vid, "page_id": page_id,
            "sha256": self.field.manifest[page_id].sha256, "via": via,
            "score_contract": scores.CONTRACT, "score_snapshot": score_state["config"],
            "score_config_sha256": score_state["config_sha256"], "score_after": score_state,
            "retained_content": {self._version(page.id): {"page_id": page.id, "text": page.text,
                                                          "sha256": page.sha256, "retained": True}
                                 for page in self.field.manifest.values()},
        }, revision_after=1, core_dir=self.core_dir, expected_seq=0)
        self._project(session_id, event)
        return self.resume_session(session_id)

    def resume_session(self, session_id: str) -> dict:
        state = self.state(session_id)
        return {"session_id": session_id, "state": state.canonical(), "revision": state.r, "active_version": state.v,
                "active_page": state.page, "paused": state.paused, "encounters": state.H,
                "offer_sets_at_revision": sorted(state.offer_sets)}

    def resolve_options(self, session_id: str, operator: str, *, policy: str = DEFAULT_POLICY) -> dict:
        state = self.state(session_id)
        if "config" not in state.z:
            return self._resolve_legacy_options(session_id, operator, policy=policy)
        if operator not in OPERATORS:
            raise CoreError("unknown_operator", f"unknown operator {operator!r}", status=400)
        if state.paused:
            raise CoreError("paused", "the session is paused; resume before resolving options")
        if self._version(state.page) != state.v:
            raise CoreError("source_version_changed", "the active exact text has changed")
        candidates, inputs, options = self._frozen_candidates(state, operator, policy)
        result = resolver.resolve(state, candidates, inputs)
        fingerprint = identity._digest({"candidate_inputs": candidates, "resolver_inputs": inputs,
                                        "score_config_sha256": state.z["config_sha256"], **result})
        offer_set_id = "offers_" + identity._digest({
            "session_id": session_id, "revision": state.r, "source_version": state.v, "operator": operator,
            "policy": policy, "score_config_sha256": state.z["config_sha256"], "decision_fingerprint": fingerprint,
        })[:20]
        existing = self._find_offer_set(session_id, offer_set_id)
        if existing is not None and scores.availability(state.z, result["blocked"]) == state.z:
            return {**existing, "reused": True}
        payload = {
            "offer_set_id": offer_set_id, "revision": state.r, "source_version": state.v, "source_page": state.page,
            "operator": operator, "policy": policy, "bond_version_ids": [bond["bond_version_id"] for bond in result["bonds"]],
            **result, "candidate_inputs": candidates, "resolver_inputs": inputs, "resolver_version": resolver.VERSION,
            "score_config_sha256": state.z["config_sha256"], "decision_fingerprint": fingerprint,
            "options_policy_version": options.get("policy_version"), "options_state": "blocked" if result["blocked"] else "options",
            "counts": options.get("counts"), "atlas_config_id": options.get("atlas_config_id"),
            "atlas_rubric_version": options.get("atlas_rubric_version"),
            "pinned_returned_model": options.get("pinned_returned_model"), "field_policy_version": "field-policy/1",
            "support_floor": options.get("support_floor"),
            "retained_content": self._retain_new_versions(session_id, [candidate["destination_page"] for candidate in candidates]),
            "unusable": options.get("unusable"),
            "exclusions": {"ineligible_policy": sum(not candidate["policy_allowed"] for candidate in candidates),
                           "unusable": sum(not candidate["evidence_allowed"] for candidate in candidates)},
        }
        event = self._append(session_id, state, "offer_set_created", payload, bumps=False)
        self._project(session_id, event)
        return {**payload, "event_seq": event["seq"], "reused": False}

    def _frozen_candidates(self, state: reducer.State, operator: str, policy: str) -> tuple[list, dict, dict]:
        from ..fields import INCLUDE_ADJACENT
        if self._candidate_provider is not None:
            options = self._candidate_provider(self.field, state.page, operator, policy)
        elif self._options_provider is not None:
            options = self._options_provider(self.field, state.page, operator, INCLUDE_ADJACENT)
        else:
            from ..memory.operator_options import operator_options, MAX_SUPPORTED, MIN_SHOWN
            options = operator_options(self.field, state.page, operator, policy=INCLUDE_ADJACENT,
                                       max_supported=len(self.field.manifest), min_shown=len(self.field.manifest))
            options.update(max_supported=MAX_SUPPORTED, min_shown=MIN_SHOWN)
        eligible = set(self.field.eligible_candidate_ids(state.page, policy))
        rows = {option["destination_id"]: option for option in options.get("options") or []}
        unusable = {item["destination_id"]: item.get("status", "unavailable") for item in options.get("unusable") or []}
        candidates = []
        for destination in self.field.candidate_ids_for(state.page):
            page = self.field.manifest[destination]
            option = rows.get(destination, {})
            destination_version = self._version(destination)
            wording = bond_wording(page.text)
            if not wording:
                continue
            fit = option.get("operator_fit") or {}
            current = option.get("destination_sha256", page.sha256) == page.sha256
            source_current = option.get("source_sha256", self.field.manifest[state.page].sha256) == self.field.manifest[state.page].sha256
            evidence_allowed = bool(option.get("assessment_id")) and current and source_current
            candidates.append({
                "bond_version_id": identity.bond_version_id(source_version=state.v, destination_version=destination_version,
                                                            operator=operator, wording=wording),
                "source_version": state.v, "destination_version": destination_version, "destination_page": destination,
                "operator": operator, "wording": wording, "wording_source": WORDING_SOURCE,
                "tier": option.get("tier"), "tier_label": option.get("tier_label"),
                "operator_fit": {key: fit.get(key) for key in ("dimension", "score", "score_norm", "confidence", "nearest_level")},
                "cautions": list(option.get("cautions") or []), "assessment_id": option.get("assessment_id"),
                "rank": option.get("rank"), "rank_reasons": option.get("rank_reasons"),
                "evidence_allowed": evidence_allowed, "policy_allowed": destination in eligible,
                "evidence_code": "assessed_exact_versions" if evidence_allowed else ("version_mismatch" if not current or not source_current else unusable.get(destination, "missing_assessment")),
                "evidence": option.get("base"), "evidence_kind": option.get("evidence_kind", "decision_evidence_no_textual_span"),
            })
        return candidates, {"operator": operator, "policy": policy,
                            "max_supported": options.get("max_supported"), "min_shown": options.get("min_shown")}, options

    def _resolve_legacy_options(self, session_id: str, operator: str, *, policy: str = DEFAULT_POLICY) -> dict:
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
        if "config" in state.z:
            if full.get("score_config_sha256") != state.z["config_sha256"]:
                reject("score_mismatch", "the offer belongs to a different score configuration")
            resolved = resolver.resolve(state, full["candidate_inputs"], full["resolver_inputs"])
            if bond_version_id not in [candidate["bond_version_id"] for candidate in resolved["bonds"]]:
                reject("score_ineligible", "this choice is unavailable under the current movement and history",
                       decisions=resolved["decisions"])

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

    def relocate(self, session_id: str, *, page_id: str, expected_revision: int, request_id: str,
                 cause: str) -> dict:
        """An intentional manual move to another exact content version within the SAME
        session. It asserts no literary relationship: no operator, no bond, no offer set.
        Same discipline as execute_action: dedup first, then validation, then one atomic
        journal append, then projections. Moving to the already-active exact version is a
        no-op (no event, no encounter) -- an explicit reread would be a separate action."""
        if not request_id or not isinstance(request_id, str):
            raise CoreError("missing_request_id", "a relocation needs a request_id", status=400)
        if cause not in RELOCATION_CAUSES:
            raise CoreError("unknown_cause", f"unknown relocation cause {cause!r}", status=400)
        state = self.state(session_id)
        fingerprint = identity.request_fingerprint({
            "session_id": session_id, "relocate_to": page_id, "expected_revision": expected_revision, "cause": cause,
        })

        # (1) deduplication, before any staleness check
        prior = self.get_action_status(session_id, request_id)
        if prior["status"] == "committed":
            if prior["fingerprint"] != fingerprint:
                raise CoreError("request_id_reused", "this request_id was already used for a different action",
                                details={"recorded": prior})
            return {"status": "committed", "duplicate": True, "noop": False, "request_id": request_id, **prior,
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
                          "kind": "relocation", "relocate_to": page_id, "cause": cause,
                          "expected_revision": expected_revision, "revision_at_rejection": state.r}, bumps=False)
            raise CoreError(code, reason, details=details)

        if state.paused:
            reject("paused", "the session is paused; navigation is rejected until it is resumed")
        if expected_revision != state.r:
            reject("stale_revision", f"expected revision {expected_revision} but the session is at {state.r}",
                   current_revision=state.r)
        try:
            self.check_relocation(session_id)
        except CoreError as error:
            reject(error.code, str(error), **error.details)
        page = self.field.manifest.get(page_id)
        if page is None:
            reject("unknown_page", f"{page_id!r} is not in field {self.field.id!r}")
        if page.is_empty:
            reject("destination_version_unavailable", f"{page_id} has no text in the current corpus")
        if self._version(state.page) != state.v:
            reject("source_version_changed", f"{state.page} is no longer the text the session is on")
        to_version = self._version(page_id)  # pinned at commit: the exact version arrived at
        if to_version == state.v:
            return {"status": "noop", "duplicate": False, "noop": True, "request_id": request_id,
                    "reason": "already at this exact version; no encounter is created by rendering it again",
                    "to_version": to_version, "to_page": page_id, "revision_after": state.r,
                    "state": state.canonical()}

        # (3) atomic commit
        event = self._append(session_id, state, "relocation_committed", {
            "request_id": request_id, "fingerprint": fingerprint, "cause": cause, "operator": None,
            "bond_version_id": None, "offer_set_id": None,
            "from_version": state.v, "from_page": state.page, "to_version": to_version, "to_page": page_id,
            "expected_revision": expected_revision, "encounter_index": len(state.H),
            **({"retained_content": self._retain_new_versions(session_id, [page_id])} if "config" in state.z else {}),
        }, bumps=True)

        # (4) projections
        projection_errors = self._project(session_id, event)
        new_state = self.state(session_id)
        return {"status": "committed", "duplicate": False, "noop": False, "request_id": request_id,
                "event_seq": event["seq"], "cause": cause, "to_version": to_version, "to_page": page_id,
                "revision_after": new_state.r, "encounter_index": len(new_state.H) - 1,
                "state": new_state.canonical(), "projection_errors": projection_errors}

    def check_relocation(self, session_id: str) -> None:
        state = self.state(session_id)
        if state.paused:
            raise CoreError("paused", "Resume this journey before moving.")
        checks = scores.evaluate(state, {}, "relocation")
        denied = next((check for check in checks if not check["allowed"]), None)
        if denied:
            raise CoreError(denied["code"], "This journey follows its offered choices. Leave the demonstration to browse freely.",
                            details={"decisions": checks})

    def lifecycle(self, session_id: str, *, action: str, expected_revision: int, request_id: str,
                  resume_session_id: str | None = None) -> dict:
        if not request_id or not isinstance(request_id, str):
            raise CoreError("missing_request_id", "a lifecycle action needs a request_id", status=400)
        if action not in ("end_journey", "exit"):
            raise CoreError("unknown_action", f"unknown lifecycle action {action!r}", status=400)
        state = self.state(session_id)
        fingerprint = identity.request_fingerprint({"session_id": session_id, "action": action,
                                                     "expected_revision": expected_revision,
                                                     **({"resume_session_id": resume_session_id} if resume_session_id else {})})
        prior = self.get_action_status(session_id, request_id)
        if prior["status"] != "unknown":
            if prior["fingerprint"] != fingerprint:
                raise CoreError("request_id_reused", "this request_id already identifies another action")
            if prior["status"] == "rejected":
                raise CoreError(prior["code"], prior["reason"], details={"duplicate": True})
            return {**self.resume_session(session_id), "duplicate": True, "result": prior}
        def reject(code, reason):
            self._append(session_id, state, "action_rejected", {
                "kind": "lifecycle", "action": action, "request_id": request_id, "fingerprint": fingerprint,
                "code": code, "reason": reason, "expected_revision": expected_revision,
            }, bumps=False)
            raise CoreError(code, reason)
        if expected_revision != state.r:
            reject("stale_revision", f"expected revision {expected_revision} but the session is at {state.r}")
        if "config" not in state.z or action not in state.z["config"]["global_actions"]:
            reject("action_forbidden", "this score does not permit that lifecycle action")
        if resume_session_id:
            if (action != "exit" or not isinstance(resume_session_id, str) or resume_session_id == session_id or not SESSION_ID_RE.match(resume_session_id)
                    or not journal.read_events(resume_session_id, self.core_dir)):
                reject("invalid_continuation", "the journey to resume must identify another recorded journey")
        event = self._append(session_id, state, "performance_ended", {
            "request_id": request_id, "fingerprint": fingerprint, "action": action,
            "prior_outcome": state.z["status"], "expected_revision": expected_revision,
            **({"continuation": {"kind": "resume_existing_journey", "session_id": resume_session_id}}
               if resume_session_id else {}),
        }, bumps=True)
        self._project(session_id, event)
        return {**self.resume_session(session_id), "duplicate": False}

    def _check_lifecycle(self, state: reducer.State, action: str) -> None:
        if "config" in state.z:
            if state.z["status"] in scores.TERMINAL_STATUSES:
                raise CoreError("performance_finished", "This journey has finished; leave it to continue reading.")
            if action not in state.z["config"]["global_actions"]:
                raise CoreError("action_forbidden", f"this score does not permit {action}")

    def pause(self, session_id: str) -> dict:
        state = self.state(session_id)
        self._check_lifecycle(state, "pause")
        if not state.paused:
            self._project(session_id, self._append(session_id, state, "paused", {}, bumps=True))
        return self.resume_session(session_id)

    def unpause(self, session_id: str) -> dict:
        state = self.state(session_id)
        self._check_lifecycle(state, "resume")
        if state.paused:
            self._project(session_id, self._append(session_id, state, "resumed", {}, bumps=True))
        return self.resume_session(session_id)

    def acknowledge_presented(self, session_id: str, offer_set_id: str) -> dict:
        """Reader-render acknowledgement: creation is not presentation. No state change."""
        state = self.state(session_id)
        if offer_set_id not in state.offer_sets:
            raise CoreError("unknown_or_stale_offer_set", f"{offer_set_id} is not current")
        return self._append(session_id, state, "presented", {"offer_set_id": offer_set_id}, bumps=False)
