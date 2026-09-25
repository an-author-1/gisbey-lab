"""Minimal local browser reader for Gibsey Lab.

Pure Python standard library (http.server) -- no new dependencies. Bound to 127.0.0.1
only. Reuses gibsey_lab.fields / reader_context / runner / recorder / state / saved_runs
/ reviewing / session_log unchanged in their public contracts.

Guarantees:
- The default exploration surface is GET /api/operator-options: a ranked list of at least
  three destinations per operator, read from the saved atlas with NO provider call. Weak
  fits are labeled exploratory, never hidden; they preview and follow like any other.
- Provider work happens ONLY inside three POST endpoints, each reached only by an explicit
  user action: POST /api/request-selection (one single-pick Choice request -- a secondary
  research action whose abstentions never hide the ranked options), POST /api/offers (one
  history-conditioned hand) and POST /api/refine-options (re-order a displayed option
  list using the reading history; it never removes an option, and any failure keeps the
  base order, labeled as such). No GET endpoint, page load, refresh, or navigation ever
  dispatches provider work.
- Single-flight: a second identical request (same kind, field, page, operator, policy,
  criteria version) that arrives while the first is in flight JOINS it -- one dispatch,
  one recorded run, one outcome line listing every joined `request_id`.
- Every request outcome -- selection, abstention, empty candidate list, provider error,
  server-side exception -- is appended to reader_outcomes.jsonl (reader/outcomes.py).
  Reruns append; earlier outcomes are never replaced.
- Every response echoes the caller's `request_id` and says whether it is still
  `applicable` (latest request for that page/operator, and the reader is still on that
  page). A superseded response is persisted all the same, but must not be rendered and
  can never cause movement.
- Follow-time validation (state.validate_movement) runs before ANY movement, on both
  follow endpoints. A failure is a 409 and moves nothing. Proposal, acceptance and
  traversal stay three separately recorded steps; following is idempotent per
  `follow_token`.
- Assessments and offers are evidence for possible bonds -- never bonds, human
  judgments, or reader preferences. No generated rationale prose is produced or served.
"""
from __future__ import annotations

import copy
import hashlib
import json
import mimetypes
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import fields as fields_module
from .. import reader_context, relational_operators, saved_runs, session_log, state
from ..config import load_config
from ..context import CaseError
from ..core import core as core_module
from ..core import identity, journal, projectors, reducer
from ..core.core import CoreError
from ..corpus import REPO_ROOT
from ..fields import FieldError
from ..jev_client import JevError
from ..recorder import RUNS_DIR
from ..reviewing import ReviewError, update_review
from ..runner import run_case
from ..validate import ProviderResultError
from . import outcomes

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Module-level (not bound default args) so tests can point these at a tmp_path without
# ever touching the real project data/ or runs/ directories.
DATA_DIR = state.DEFAULT_DATA_DIR
RUNS_DIR = RUNS_DIR
SESSION_LOG_PATH = session_log.DEFAULT_LOG_PATH
# Where the Core's per-session journals live (data/core/sessions/<id>/events.jsonl).
CORE_DIR = journal.DEFAULT_CORE_DIR
# None = "<DATA_DIR>/<file>", resolved at call time, so pointing DATA_DIR at a temp
# directory isolates these too. Set explicitly to override.
OUTCOMES_PATH: Path | None = None
OFFER_SETS_PATH: Path | None = None
OPTION_SETS_PATH: Path | None = None
# Which atlas the ranked operator options are read from ("live"; a smoke run uses "mock").
OPTIONS_MODE = "live"
SERVER_STARTED_AT = datetime.now(timezone.utc).isoformat()
DEMO_DIR = REPO_ROOT / "data" / "demos" / "pr2_memory"

OFFER_SET_SCHEMA = "reader-offer-set/1"
MEMORY_NOT_CURRENT_NOTE = ("Computed for an earlier reading history \u2014 ask again for routes informed by "
                           "how you got here this time")
JOIN_TIMEOUT_SECONDS = 600.0
ATLAS_DIMENSIONS = (
    "direct_q_fit", "echo", "development", "contradiction", "bridge_relation", "redundancy", "missing_context",
)


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, payload: dict | None = None):
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


# --- hooks the lead wires / tests override (B's and C's packages are imported lazily) ---

def _default_offers_builder(field, page_id, events, **kwargs) -> dict:
    from ..memory.offers import build_offers  # lazy: worker C's package

    return build_offers(field, page_id, events, **kwargs)


def _default_profiles_provider(source_id: str, mode: str) -> list[dict]:
    from ..atlas import api as atlas_api  # lazy: worker B's package

    return atlas_api.profiles_for_source(source_id, mode)


def _default_offer_dispatch_factory():
    raise ApiError(
        "live offer dispatch is lead-wired: server.OFFER_DISPATCH_FACTORY has not been set, "
        "so no contextual assessment can be requested",
        status=503,
    )


def _default_options_provider(field, page_id: str, operator: str, *, policy: str, mode: str) -> dict:
    from ..memory.operator_options import operator_options  # lazy: the selection worker's module

    return operator_options(field, page_id, operator, policy=policy, mode=mode)


def _default_options_refiner(option_set: dict, field, events: list[dict], **kwargs) -> dict:
    from ..memory.operator_options import refine_with_history  # lazy

    return refine_with_history(option_set, field, events, **kwargs)


def _default_encounter_counter(field, page_id: str, events: list[dict], *, policy: str, intention: str | None) -> int | None:
    from ..memory.packet import build_memory_packet  # lazy

    packet = build_memory_packet(field, page_id, events, candidate_policy=policy, intention=intention)
    return len(packet.get("encounters") or [])


# OPTIONS_PROVIDER(field, page_id, operator, *, policy, mode) -> operator-options/1 dict   (never dispatches)
OPTIONS_PROVIDER = _default_options_provider
# OPTIONS_REFINER(option_set, field, events, *, dispatch, mode, requested_model, intention) -> same set + contextual
OPTIONS_REFINER = _default_options_refiner
# ENCOUNTER_COUNTER(field, page_id, events, *, policy, intention) -> int | None   (never dispatches)
ENCOUNTER_COUNTER = _default_encounter_counter


def _default_memory_hasher(field, page_id: str, events: list[dict], *, policy: str, intention: str | None) -> str:
    """sha256 of the memory the provider WOULD be shown right now -- computed exactly as
    memory.offers.build_offers does (same packet builder, same hash), without dispatching."""
    from ..memory.packet import build_memory_packet, memory_sha256  # lazy: worker C's package

    return memory_sha256(build_memory_packet(field, page_id, events, candidate_policy=policy, intention=intention))


# MEMORY_HASHER(field: Field, page_id, events, *, policy, intention) -> str   (never dispatches)
MEMORY_HASHER = _default_memory_hasher
# OFFERS_BUILDER(field: Field, page_id: str, events: list[dict], *, policy, dispatch, mode,
#                requested_model, intention=None) -> offer-result/1 dict
OFFERS_BUILDER = _default_offers_builder
# PROFILES_PROVIDER(source_id: str, mode: "live"|"mock") -> list[dict] (40 rows)
PROFILES_PROVIDER = _default_profiles_provider
# OFFER_DISPATCH_FACTORY() -> (dispatch, mode, requested_model)
OFFER_DISPATCH_FACTORY = _default_offer_dispatch_factory


def _outcomes_path() -> Path:
    if OUTCOMES_PATH is not None:
        return Path(OUTCOMES_PATH)
    if outcomes.OUTCOMES_PATH != outcomes.DEFAULT_OUTCOMES_PATH:
        return Path(outcomes.OUTCOMES_PATH)
    return Path(DATA_DIR) / "reader_outcomes.jsonl"


def _option_sets_path() -> Path:
    return Path(OPTION_SETS_PATH) if OPTION_SETS_PATH is not None else Path(DATA_DIR) / "reader_option_sets.jsonl"


def _offer_sets_path() -> Path:
    return Path(OFFER_SETS_PATH) if OFFER_SETS_PATH is not None else Path(DATA_DIR) / "reader_offer_sets.jsonl"


# --- single-flight + latest-request registry ---

class _Flight:
    def __init__(self, leader_request_id: str):
        self.done = threading.Event()
        self.request_ids = [leader_request_id]
        self.payload: dict | None = None
        self.error: ApiError | None = None


class SingleFlight:
    """At most one execution per key at a time; concurrent callers join it. A request
    that arrives after the flight has closed starts a new one (an explicit rerun)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._flights: dict[tuple, _Flight] = {}

    def in_flight(self, key: tuple) -> bool:
        with self._lock:
            return key in self._flights

    def close(self, key: tuple, flight: _Flight) -> list[str]:
        """Stop accepting joiners; returns every request_id served by this flight."""
        with self._lock:
            if self._flights.get(key) is flight:
                del self._flights[key]
            return list(flight.request_ids)

    def run(self, key: tuple, request_id: str, work) -> tuple[dict, bool]:
        """`work(flight)` must call `self.close(key, flight)` before persisting its
        outcome (so the outcome lists every joiner). Returns (payload, joined)."""
        with self._lock:
            flight = self._flights.get(key)
            if flight is None:
                flight = _Flight(request_id)
                self._flights[key] = flight
                leader = True
            else:
                flight.request_ids.append(request_id)
                leader = False

        if not leader:
            if not flight.done.wait(JOIN_TIMEOUT_SECONDS):
                raise ApiError("timed out waiting for the identical in-flight request", status=504,
                               payload={"request_id": request_id, "state": outcomes.ERROR})
            if flight.error is not None:
                raise ApiError(str(flight.error), flight.error.status, dict(flight.error.payload))
            return copy.deepcopy(flight.payload), True

        try:
            flight.payload = work(flight)
            return copy.deepcopy(flight.payload), False
        except ApiError as e:
            flight.error = e
            raise
        except Exception as e:  # noqa: BLE001 -- joiners must never hang on a leader crash
            flight.error = ApiError(f"{type(e).__name__}: {e}", status=500)
            raise
        finally:
            self.close(key, flight)
            flight.done.set()


FLIGHTS = SingleFlight()

_LATEST_LOCK = threading.Lock()
_LATEST_REQUEST: dict[tuple, str] = {}  # (kind, field, page, operator) -> newest request_id
_FOLLOW_LOCK = threading.Lock()  # one validate->propose->accept->follow sequence at a time


def _register_latest(scope: tuple, request_id: str) -> None:
    with _LATEST_LOCK:
        _LATEST_REQUEST[scope] = request_id


def _applicability(scope: tuple, request_ids: list[str], field_id: str, page_id: str) -> tuple[bool, str | None]:
    """Is a finished request still the one the reader is waiting for? Superseded when a
    newer request was registered for the same page/operator, or when the session log
    shows the reader has since moved to another page."""
    with _LATEST_LOCK:
        latest = _LATEST_REQUEST.get(scope)
    if latest is not None and latest not in request_ids:
        return False, f"superseded by newer request {latest}"
    last = session_log.last_encounter(SESSION_LOG_PATH, field=field_id)
    if last is not None and last.get("page_id") and last.get("page_id") != page_id:
        return False, f"the reader has moved to {last.get('page_id')}"
    return True, None


def _new_request_id(body: dict) -> str:
    request_id = body.get("request_id")
    return str(request_id) if request_id else f"srv_{uuid.uuid4().hex[:12]}"


def _wait_for_free_run_slot(case_id: str) -> None:
    """recorder.record_run names a run dir by whole-second timestamp + case id and refuses
    to overwrite. Same-case runs are already serialized by single-flight; this only makes
    sure a rerun never STARTS in a second that already holds a run dir for the case, so
    its own (later) record can never collide with it."""
    runs_dir = Path(RUNS_DIR)
    for _ in range(40):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if not runs_dir.is_dir() or not any(runs_dir.glob(f"{stamp}_{case_id}_*")):
            return
        time.sleep(0.05)


def _field_manifest_hashes(field) -> dict[str, str]:
    return {pid: p.sha256 for pid, p in field.manifest.items()}


def _load_field(field_id: str):
    try:
        return fields_module.load_field(field_id)
    except FieldError as e:
        raise ApiError(str(e)) from e


def _title_of(page_id: str) -> str:
    prefix = fields_module.prefix_of(page_id)
    return next((title for p, title in fields_module.TEXT_GROUPS if p == prefix), prefix)


def _saved_result_to_dict(saved: saved_runs.SavedResult | None) -> dict:
    if saved is None:
        return {"recorded": False, "state": outcomes.NOT_REQUESTED}
    return {
        "recorded": True,
        "kind": "recorded",
        "state": outcomes.ABSTAINED if saved.is_abstention else outcomes.SELECTED,
        "run_id": saved.run_id,
        "run_dir": str(saved.run_dir),
        "field": saved.field,
        "source": saved.source_id,
        "operator": saved.operator,
        "criterion": saved.criterion,
        "is_abstention": saved.is_abstention,
        "selected_id": saved.selected_id,
        "selected_text": saved.selected_text,
        "confidence": saved.confidence,
        "probabilities": saved.probabilities,
        "requested_model": saved.requested_model,
        "returned_model": saved.returned_model,
        "elapsed_seconds": saved.elapsed_seconds,
        "usage": saved.usage,
    }


def _run_outcome_to_dict(run_dir: Path) -> dict:
    input_record = json.loads((run_dir / "input.json").read_text())
    response = json.loads((run_dir / "response.json").read_text())
    result = json.loads((run_dir / "result.json").read_text())
    return {
        "run_id": input_record["run_id"],
        "run_dir": str(run_dir),
        "field": input_record.get("reader_state", {}).get("field"),
        "source": input_record["source_id"],
        "operator": input_record.get("reader_state", {}).get("operator"),
        "criterion": input_record["criterion"],
        "kind": "mock" if response.get("live") is False else "new",
        "live": response.get("live"),
        "requested_model": response.get("requested_model"),
        "returned_model": response.get("returned_model"),
        "elapsed_seconds": response.get("elapsed_seconds"),
        "usage": response.get("usage"),
        "error": response.get("error"),
        "result": result,  # None if the run failed/errored
    }


def _log_operator_result(kind: str, field_id: str, source_id: str, operator: str, record: dict, **extra) -> None:
    result = record.get("result") if "result" in record else record
    session_log.append_event(
        "operator_result",
        log_path=SESSION_LOG_PATH,
        field=field_id,
        source=source_id,
        operator=operator,
        kind=kind,
        run_dir=record.get("run_dir"),
        destination=None if result is None else result.get("selected_id"),
        is_abstention=None if result is None else result.get("is_abstention"),
        confidence=None if result is None else result.get("confidence"),
        error=record.get("error"),
        **extra,
    )


def _memory_currency(result: dict, field) -> tuple[bool | None, str | None]:
    """Was this persisted hand computed for the reading history the reader has NOW?
    (True/False, current hash); (None, None) when the hand recorded no memory hash. A hand
    whose current memory cannot be recomputed is not current. Viewing or previewing a hand
    adds no encounter, so it never changes this by itself."""
    recorded = result.get("memory_sha256")
    if not recorded:
        return None, None
    packet = result.get("memory_packet") if isinstance(result.get("memory_packet"), dict) else {}
    try:
        current = MEMORY_HASHER(
            field, result.get("page_id"), session_log.read_events_with_seq(SESSION_LOG_PATH),
            policy=result.get("policy"), intention=packet.get("intention"),
        )
    except Exception:  # noqa: BLE001 -- unverifiable is treated as not current, never as current
        return False, None
    return current == recorded, current


def _position_conflict(field_id: str, this_page: str, action: str) -> tuple[str, dict] | None:
    """(message, payload) when the session log does not place the reader on `this_page`."""
    last = session_log.last_encounter(SESSION_LOG_PATH, field=field_id)
    logged = last.get("page_id") if last else None
    if logged == this_page:
        return None
    message = outcomes.describe_position_conflict(this_page, logged, action)
    return message, {"position_conflict": {"field": field_id, "this_page": this_page, "logged_page": logged}}


def _check_reader_is_on(field_id: str, from_page: str) -> None:
    """Follow paths: refuse (409, nothing moved) when the log places the reader elsewhere.
    With no recorded visit at all there is nothing to contradict, so the follow proceeds."""
    if session_log.last_encounter(SESSION_LOG_PATH, field=field_id) is None:
        return
    conflict = _position_conflict(field_id, from_page, "followed")
    if conflict is not None:
        raise ApiError(conflict[0], status=409, payload=conflict[1])


def _log_follow_events(*, proposal_kind: str, field_id, source_id, destination_id, policy, operator,
                       relation_labels, run_dir, offer_set_id, proposal_id, bond_id, follow_token,
                       source_sha256, destination_sha256, stage: str, extra: dict | None = None) -> None:
    common = dict(
        log_path=SESSION_LOG_PATH, field=field_id, source=source_id, destination=destination_id,
        operator=operator, policy=policy, proposal_kind=proposal_kind, run_dir=run_dir,
        offer_set_id=offer_set_id, proposal_id=proposal_id, request_id=follow_token,
    )
    if relation_labels is not None:
        common["relation_labels"] = list(relation_labels)
    common.update(extra or {})  # e.g. tier / operator_fit / option_set_id of a followed operator option
    if stage == "proposed":
        session_log.append_event(
            "offer_proposed" if proposal_kind == "offer" else "operator_proposed",
            page_sha256=source_sha256, destination_sha256=destination_sha256, **common,
        )
    elif stage == "accepted":
        session_log.append_event("offer_accepted", bond_id=bond_id, page_sha256=source_sha256, **common)
    elif stage == "followed":
        # Legacy mirror first (session_review and older log readers key on this name),
        # then the traversal itself immediately before the view it caused.
        session_log.append_event(session_log.TRAVERSAL_EVENT, bond_id=bond_id, page_sha256=source_sha256, **common)
        session_log.append_event(
            session_log.Q_TRAVERSAL_EVENT, bond_id=bond_id, from_page=source_id,
            page_sha256=source_sha256, destination_sha256=destination_sha256, **common,
        )
        session_log.append_event(
            "page_viewed", log_path=SESSION_LOG_PATH, field=field_id, page_id=destination_id,
            from_page=source_id, via="traversal", page_sha256=destination_sha256, policy=policy,
            operator=operator, bond_id=bond_id, request_id=follow_token, proposal_kind=proposal_kind,
            **({"relation_labels": list(relation_labels), "offer_set_id": offer_set_id} if proposal_kind == "offer" else {}),
            **(extra or {}),
        )


def _strip_memory_texts(result: dict) -> dict:
    """Response copy of an OfferResult without the encounter texts (the persisted line
    keeps them). Adds a small text-free memory summary for the details panel."""
    view = copy.deepcopy(result)
    packet = view.get("memory_packet") if isinstance(view.get("memory_packet"), dict) else {}
    encounters = packet.get("encounters") or []
    for encounter in encounters:
        if isinstance(encounter, dict):
            encounter.pop("text", None)
    view["memory_summary"] = {
        "encounters_supplied": len(encounters),
        "encounters_omitted": packet.get("omitted_earlier_encounters"),
        "encounter_page_ids": [e.get("page_id") for e in encounters if isinstance(e, dict)],
        "intention_supplied": bool(packet.get("intention")),
        "memory_sha256": view.get("memory_sha256"),
        "source": packet.get("source"),
    }
    return view


def _offer_view(result: dict, *, field=None) -> dict:
    """What the browser gets for an offer hand: the OfferResult (minus memory texts), the
    plain-wording headline, and the exact current authored text of each offered page."""
    view = _strip_memory_texts(result)
    view["message"] = outcomes.describe_offer_outcome(result)
    display = {}
    stale = False
    if field is None:
        try:
            field = fields_module.load_field(result.get("field") or fields_module.DEFAULT_FIELD)
        except FieldError:
            field = None
    if field is not None:
        page = field.manifest.get(result.get("page_id"))
        if page is None or (result.get("page_sha256") and page.sha256 != result.get("page_sha256")):
            stale = True
        for offer in result.get("offers") or []:
            dest_id = offer.get("destination_id")
            dest = field.manifest.get(dest_id)
            matches = dest is not None and dest.sha256 == offer.get("destination_sha256")
            display[dest_id] = {
                "title": _title_of(dest_id) if dest_id else None,
                "text": dest.text if matches else None,  # never show a different version as if assessed
                "version_matches": matches,
            }
            stale = stale or not matches
    view["reader_display"] = display
    view["stale"] = stale
    if field is not None:
        view["memory_current"], view["current_memory_sha256"] = _memory_currency(result, field)
    else:
        view["memory_current"], view["current_memory_sha256"] = False, None
    if view["memory_current"] is False:
        view["memory_note"] = MEMORY_NOT_CURRENT_NOTE
    return view


def _read_offer_sets() -> list[dict]:
    path = _offer_sets_path()
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and isinstance(record.get("result"), dict):
            records.append(record)
    return records


_OFFER_SETS_LOCK = threading.Lock()


def _append_offer_set(result: dict, *, request_ids: list[str], outcome_id: str) -> None:
    path = _offer_sets_path()
    line = {"schema": OFFER_SET_SCHEMA, "offer_set_id": result.get("offer_set_id"), "at": result.get("at"),
            "request_ids": request_ids, "outcome_id": outcome_id, "result": result}
    with _OFFER_SETS_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


_OPTION_SETS_LOCK = threading.Lock()


def _read_option_records() -> list[dict]:
    path = _option_sets_path()
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and isinstance(record.get("option_set"), dict):
            records.append(record)
    return records


def _stored_option_set(option_set_id: str) -> dict | None:
    """The BASE option set as it was shown (never a refinement of it)."""
    for record in _read_option_records():
        if record.get("record_type") == "option_set" and record.get("option_set_id") == option_set_id:
            return record["option_set"]
    return None


def _persist_option_set(option_set: dict) -> bool:
    """Idempotent: an option_set_id is a content hash, so one line per distinct set."""
    option_set_id = option_set.get("option_set_id")
    with _OPTION_SETS_LOCK:
        if any(r.get("record_type") == "option_set" and r.get("option_set_id") == option_set_id
               for r in _read_option_records()):
            return False
        path = _option_sets_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"schema": "reader-option-set/1", "record_type": "option_set",
                                "option_set_id": option_set_id, "at": datetime.now(timezone.utc).isoformat(),
                                "option_set": option_set}, ensure_ascii=False) + "\n")
        return True


def _persist_refinement(option_set: dict, *, request_ids: list[str], outcome_id: str, refine_state: str) -> None:
    with _OPTION_SETS_LOCK:
        path = _option_sets_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"schema": "reader-option-set/1", "record_type": "refinement",
                                "option_set_id": option_set.get("option_set_id"), "refine_state": refine_state,
                                "at": datetime.now(timezone.utc).isoformat(), "request_ids": request_ids,
                                "outcome_id": outcome_id, "option_set": option_set}, ensure_ascii=False) + "\n")


def _option_view(option_set: dict, field, *, ordering_line: str | None = None) -> dict:
    """What the browser gets for a ranked option list: the option set, plain status and
    ordering lines, and the exact CURRENT authored text of each destination -- withheld
    when the page no longer matches the version that was assessed."""
    view = copy.deepcopy(option_set)
    display = {}
    for option in view.get("options") or []:
        dest_id = option.get("destination_id")
        dest = field.manifest.get(dest_id) if field is not None else None
        matches = dest is not None and dest.sha256 == option.get("destination_sha256")
        display[dest_id] = {"title": _title_of(dest_id) if dest_id else None,
                            "text": dest.text if matches else None, "version_matches": matches}
        fit = option.get("operator_fit") if isinstance(option.get("operator_fit"), dict) else {}
        # The word names the rubric level the score CLEARS (floor, never rounding), so an
        # exploratory row can never carry a word a supported row carries. Numbers untouched.
        option["fit_level"] = {"level_cleared": outcomes.level_cleared(fit.get("score")),
                               "name": outcomes.level_name(fit.get("dimension") or view.get("dimension"), fit.get("score"))}
    view["reader_display"] = display
    view["order_changed"] = False
    view["message"] = outcomes.describe_option_set(option_set)
    view["ordering_line"] = ordering_line or outcomes.describe_ordering(option_set)
    return view


def _unavailable_option_set(field, page_id: str, operator: str, policy: str, mode: str, error: str) -> dict:
    return {
        "schema": "operator-options/1", "option_set_id": f"unavailable_{uuid.uuid4().hex[:12]}", "field": field.id,
        "page_id": page_id, "page_sha256": field.manifest[page_id].sha256, "operator": operator, "policy": policy,
        "mode": mode, "ordering_basis": "base_assessments", "state": "atlas_unavailable", "error": error,
        "counts": {}, "unusable": [], "options": [], "synthesized_by": "reader-server",
    }


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5)
    except Exception:  # noqa: BLE001 -- build identity is informational only
        return None
    return out.stdout if out.returncode == 0 else None


# --- Core (v0.3): validated actions, one atomic journal append per commit, legacy mirrors ---

# One Core call at a time in this process: the journal's own expected-seq check would turn
# a concurrent second tab into a JournalError; serialized, it becomes the Core's own
# `stale_revision` refusal instead. Re-entrant so a handler may compose helpers.
_CORE_LOCK = threading.RLock()


def _core(field=None) -> core_module.Core:
    """A Core over CORE_DIR. Offers come from the same options provider the ranked lists use
    (never a dispatch); after every commit the legacy stores under DATA_DIR / SESSION_LOG_PATH
    are mirrored so the existing panels keep working. Stateless: the journal is re-read on
    every call, so a new instance per request is a restart-equivalent."""
    field = field if field is not None else _load_field(fields_module.DEFAULT_FIELD)
    return core_module.Core(
        core_dir=Path(CORE_DIR), field=field,
        options_provider=lambda f, page_id, operator, policy: OPTIONS_PROVIDER(f, page_id, operator, policy=policy, mode=OPTIONS_MODE),
        projectors=[projectors.mirror_to_legacy_stores(Path(DATA_DIR), Path(SESSION_LOG_PATH), field=field)],
    )


def _session_events(session_id: str | None) -> list[dict]:
    if not session_id or not core_module.SESSION_ID_RE.match(session_id):
        return []
    try:
        return journal.read_events(session_id, Path(CORE_DIR))
    except journal.JournalError as e:
        raise ApiError(f"the session journal is unreadable: {e}", status=500) from e


def _core_for_session(session_id: str | None) -> core_module.Core:
    """The Core for an existing session, over the field the session was started in."""
    events = _session_events(session_id)
    field_id = events[0].get("field_id") if events else None
    return _core(_load_field(field_id) if field_id in fields_module.KNOWN_FIELDS else None)


def _core_error(e: CoreError) -> ApiError:
    return ApiError(str(e), status=e.status, payload={"code": e.code, "reason": str(e), "details": e.details})


def _position_advisory(field_id: str, session_page: str | None) -> dict:
    """Where the legacy session log last placed the reader, next to where the Core session
    is. Advisory only: the Core's revision check is the authority on whether an action runs."""
    last = session_log.last_encounter(SESSION_LOG_PATH, field=field_id)
    logged = last.get("page_id") if last else None
    return {"logged_page": logged, "session_page": session_page,
            "agrees": logged is None or session_page is None or logged == session_page}


def _session_view(core: core_module.Core, session_id: str, **extra) -> dict:
    view = core.resume_session(session_id)
    view["encounter_count"] = len(view["encounters"])
    view["field"] = core.field.id
    # The offer sets resolved at the current revision, in creation order (a reload can show
    # the last one again with a plain re-resolve, which creates nothing).
    view["current_offer_sets"] = [{"offer_set_id": k, **v} for k, v in view["state"]["offer_sets"].items()]
    view["position"] = _position_advisory(core.field.id, view.get("active_page"))
    view["journey_url"] = f"/journey?session_id={session_id}"
    view.update(extra)
    return view


def _reader_last_page(field) -> str:
    """The page the reader was last recorded on: the session log, else the recorded Q
    position, else the field's first page."""
    last = session_log.last_encounter(SESSION_LOG_PATH, field=field.id)
    if last and last.get("page_id") in field.manifest:
        return last["page_id"]
    active = state.reader_state(data_dir=DATA_DIR).get("active_page")
    if active in field.manifest:
        return active
    return field.all_ids()[0]


def _core_options_view(offer_set: dict, field) -> dict:
    """What the browser gets for a Core offer set: the persisted set, plus per bond the exact
    CURRENT text of its destination (withheld if the version no longer matches), the rubric
    level word its score clears, and the same status/ordering lines the ranked list shows."""
    view = copy.deepcopy(offer_set)
    display = {}
    for bond in view.get("bonds") or []:
        dest_id = bond.get("destination_page")
        dest = field.manifest.get(dest_id)
        matches = dest is not None and identity.version_id(dest_id, dest.sha256) == bond.get("destination_version")
        bond["destination_id"] = dest_id
        bond["destination_sha256"] = dest.sha256 if matches else None
        display[dest_id] = {"title": _title_of(dest_id) if dest_id else None,
                            "text": dest.text if matches else None, "version_matches": matches}
        fit = bond.get("operator_fit") if isinstance(bond.get("operator_fit"), dict) else {}
        bond["fit_level"] = {"level_cleared": outcomes.level_cleared(fit.get("score")),
                             "name": outcomes.level_name(fit.get("dimension"), fit.get("score"))}
    view["reader_display"] = display
    view["ordering_basis"] = "base_assessments"
    view["order_changed"] = False
    view["field"] = field.id
    view["page_id"] = view.get("source_page")
    view["state"] = view.get("options_state")
    described = {"state": view["state"], "counts": view.get("counts"), "options": view.get("bonds"),
                 "operator": view.get("operator"), "page_id": view.get("source_page"), "policy": view.get("policy")}
    view["message"] = outcomes.describe_option_set(described)
    view["ordering_line"] = outcomes.describe_ordering(described)
    view["evidence_note"] = ("decision evidence (model distribution) — no textual evidence span recorded")
    return view


class Handlers:
    """Route implementations, kept separate from HTTP plumbing for testability."""

    @staticmethod
    def get_build(_query: dict) -> dict:
        """Which build is actually being served (read-only `git rev-parse` / `git status`)."""
        revision = _git("rev-parse", "HEAD")
        status = _git("status", "--porcelain", "--untracked-files=no")
        app_js = STATIC_DIR / "app.js"
        return {
            "git_revision": revision.strip() if revision else None,
            "dirty": None if status is None else bool(status.strip()),
            "app_js_sha256": hashlib.sha256(app_js.read_bytes()).hexdigest() if app_js.is_file() else None,
            "server_started_at": SERVER_STARTED_AT,
        }

    @staticmethod
    def _options_request(query_or_body: dict, *, from_query: bool) -> tuple:
        get = (lambda k, d=None: query_or_body.get(k, [d])[0]) if from_query else (lambda k, d=None: query_or_body.get(k, d))
        field_id = get("field", fields_module.DEFAULT_FIELD)
        page_id = get("page") or get("source")
        operator = get("operator")
        policy = get("policy", fields_module.DEFAULT_POLICY)
        if not page_id or not operator:
            raise ApiError("missing 'page' or 'operator'")
        operator = str(operator).upper()
        if operator not in relational_operators.OPERATOR_NAMES:
            raise ApiError(f"unknown operator: {operator!r}")
        if policy not in fields_module.KNOWN_POLICIES:
            raise ApiError(f"unknown candidate policy: {policy!r}")
        field = _load_field(field_id)
        if page_id not in field.manifest:
            raise ApiError(f"page {page_id!r} not in field {field.id!r}", status=404)
        return field, page_id, operator, policy

    @staticmethod
    def get_operator_options(query: dict) -> dict:
        """The ranked destinations for one operator from the saved atlas. NEVER dispatches.
        Persists the option set once (idempotent by its content-hash id) and logs a passive
        `operator_options_shown` event, which is not an encounter and changes no memory."""
        field, page_id, operator, policy = Handlers._options_request(query, from_query=True)
        mode = query.get("mode", [OPTIONS_MODE])[0]
        if mode not in ("live", "mock"):
            raise ApiError(f"unknown atlas mode: {mode!r} (live or mock)")
        try:
            option_set = OPTIONS_PROVIDER(field, page_id, operator, policy=policy, mode=mode)
            if not isinstance(option_set, dict) or not isinstance(option_set.get("options"), list) or not option_set.get("option_set_id"):
                raise ValueError("the options provider returned an unusable result")
        except ApiError:
            raise
        except Exception as e:  # noqa: BLE001 -- shown plainly; never an empty, unexplained panel
            option_set = _unavailable_option_set(field, page_id, operator, policy, mode, f"{type(e).__name__}: {e}")
        if option_set.get("state") != "atlas_unavailable":
            _persist_option_set(option_set)
        session_log.append_event(
            "operator_options_shown", log_path=SESSION_LOG_PATH, field=field.id, page_id=page_id,
            page_sha256=field.manifest[page_id].sha256, operator=operator, policy=policy,
            option_set_id=option_set.get("option_set_id"), state=option_set.get("state"),
            ordering_basis=option_set.get("ordering_basis"),
            destinations=[o.get("destination_id") for o in option_set.get("options") or []],
        )
        return _option_view(option_set, field)

    @staticmethod
    def post_refine_options(body: dict) -> dict:
        """Re-order a displayed option list using the reading history. The third (and last)
        endpoint that may dispatch. It never removes an option; anything short of a valid
        answer for every displayed option keeps the base order and says so. Every outcome
        is persisted, including refusals and failures."""
        option_set_id = body.get("option_set_id")
        request_id = _new_request_id(body)
        intention = body.get("intention")
        intention = (str(intention).strip() or None) if intention is not None else None
        if not option_set_id:
            raise ApiError("missing 'option_set_id'", payload={"request_id": request_id})
        base = _stored_option_set(option_set_id)
        if base is None:
            raise ApiError(f"unknown option set: {option_set_id}", status=404, payload={"request_id": request_id})
        field = _load_field(base.get("field") or fields_module.DEFAULT_FIELD)
        page_id, operator, policy = base.get("page_id"), base.get("operator"), base.get("policy")
        scope = (outcomes.KIND_REFINEMENT, field.id, page_id, operator)
        key = (outcomes.KIND_REFINEMENT, field.id, page_id, operator, policy, (option_set_id, intention))
        _register_latest(scope, request_id)
        shown_ids = [o.get("destination_id") for o in base.get("options") or []]

        def work(flight: _Flight) -> dict:
            def finish(result: dict, refine_state: str, *, first_error: str | None = None, failed: int = 0,
                       encounters: int | None = None, status: int | None = None, extra: dict | None = None) -> dict:
                request_ids = FLIGHTS.close(key, flight)
                applicable, reason = _applicability(scope, request_ids, field.id, page_id)
                refinement = result.get("refinement") if isinstance(result.get("refinement"), dict) else {}
                memory_current = None
                if refinement.get("memory_sha256"):
                    try:
                        memory_current = MEMORY_HASHER(
                            field, page_id, session_log.read_events_with_seq(SESSION_LOG_PATH),
                            policy=policy, intention=intention) == refinement["memory_sha256"]
                    except Exception:  # noqa: BLE001
                        memory_current = False
                if memory_current is False and applicable:
                    applicable, reason = False, "the reading history changed while the refinement was running"
                # Derived from the result itself: did the order really change, and did the
                # history support any of these moves at all?
                returned_order = [o.get("destination_id") for o in result.get("options") or []]
                order_changed = refine_state == outcomes.REFINED and returned_order != shown_ids
                no_support = refine_state == outcomes.REFINED and outcomes.history_found_no_support(result.get("options"))
                message = outcomes.describe_refinement(refine_state, failed=failed, shown=len(shown_ids), first_error=first_error,
                                                       order_changed=order_changed, no_support=no_support)
                ordering_line = outcomes.describe_ordering(result, encounters_supplied=encounters, refine_state=refine_state,
                                                           order_changed=order_changed, no_support=no_support)
                outcome = outcomes.append_outcome(
                    _outcomes_path(), kind=outcomes.KIND_REFINEMENT, state=refine_state, field=field.id,
                    page_id=page_id, page_sha256=base.get("page_sha256"), operator=operator, policy=policy,
                    criteria_version=None, option_set_id=option_set_id, ordering_basis=result.get("ordering_basis"),
                    order_changed=order_changed, history_found_no_support=no_support,
                    destinations=[o.get("destination_id") for o in result.get("options") or []],
                    memory_sha256=refinement.get("memory_sha256"), encounters_supplied=encounters,
                    usage=refinement.get("usage") or result.get("usage"), error=first_error,
                    request_id=request_ids[0], request_ids=request_ids, applicable=applicable,
                    not_applicable_reason=reason, message=message,
                )
                _persist_refinement(result, request_ids=request_ids, outcome_id=outcome["outcome_id"], refine_state=refine_state)
                session_log.append_event(
                    "operator_options_refined", log_path=SESSION_LOG_PATH, field=field.id, page_id=page_id,
                    page_sha256=base.get("page_sha256"), operator=operator, policy=policy,
                    option_set_id=option_set_id, state=refine_state, ordering_basis=result.get("ordering_basis"),
                    request_id=request_ids[0],
                )
                view = _option_view(result, field, ordering_line=ordering_line)
                view.update({"refine_state": refine_state, "refine_message": message, "outcome_id": outcome["outcome_id"],
                             "leader_request_id": request_ids[0], "request_ids": request_ids, "applicable": applicable,
                             "not_applicable_reason": reason, "memory_current": memory_current,
                             "encounters_supplied": encounters, "order_changed": order_changed,
                             "history_found_no_support": no_support, **(extra or {})})
                if status is not None:
                    raise ApiError(first_error or message, status=status, payload=view)
                return view

            conflict = _position_conflict(field.id, page_id, "requested")
            if conflict is not None:
                return finish(base, outcomes.ERROR, status=409, first_error=conflict[0], extra=conflict[1])
            try:
                dispatch, mode, requested_model = OFFER_DISPATCH_FACTORY()
                events = session_log.read_events_with_seq(SESSION_LOG_PATH)
                result = OPTIONS_REFINER(copy.deepcopy(base), field, events, dispatch=dispatch, mode=mode,
                                         requested_model=requested_model, intention=intention)
            except ApiError as e:
                return finish(base, outcomes.ERROR, first_error=str(e), status=e.status)
            except Exception as e:  # noqa: BLE001 -- recorded; the base list stays usable
                return finish(base, outcomes.ERROR, first_error=f"{type(e).__name__}: {e}", status=500)

            returned_ids = [o.get("destination_id") for o in result.get("options") or []] if isinstance(result, dict) else []
            if not isinstance(result, dict) or sorted(map(str, returned_ids)) != sorted(map(str, shown_ids)):
                # A refinement may reorder, never add or remove. Anything else is discarded.
                return finish(base, outcomes.ERROR, status=500,
                              first_error="the refinement did not return exactly the displayed options; it was discarded")
            refinement = result.get("refinement") if isinstance(result.get("refinement"), dict) else {}
            failed = [o for o in result["options"] if o.get("contextual_error") or not o.get("contextual")]
            errors = [outcomes.error_text(e) for e in refinement.get("errors") or []]
            errors += [outcomes.error_text(o["contextual_error"]) for o in failed if o.get("contextual_error")]
            if result.get("ordering_basis") == "reading_history" and not failed:
                summary = refinement.get("memory_summary") if isinstance(refinement.get("memory_summary"), dict) else {}
                if isinstance(summary.get("encounters"), list):
                    encounters = len(summary["encounters"])  # what the refiner itself says it supplied
                else:
                    try:
                        encounters = ENCOUNTER_COUNTER(field, page_id, events, policy=policy, intention=intention)
                    except Exception:  # noqa: BLE001
                        encounters = None
                return finish(result, outcomes.REFINED, encounters=encounters)
            # Not every option was assessed: keep the BASE order exactly as it was shown.
            order = {dest: i for i, dest in enumerate(shown_ids)}
            kept = dict(result)
            kept["options"] = sorted(result["options"], key=lambda o: order.get(o.get("destination_id"), len(order)))
            kept["ordering_basis"] = "base_assessments"
            refine_state = outcomes.REFINE_FAILED if len(failed) >= len(shown_ids) or refinement.get("state") == "failed" \
                else outcomes.REFINE_PARTIAL
            return finish(kept, refine_state, failed=len(failed), first_error=errors[0] if errors else None)

        return Handlers._fly(key, request_id, work)

    @staticmethod
    def post_follow_option(body: dict) -> dict:
        """Follow one row of a persisted ranked option list: same validation as
        follow-offer, then propose -> accept -> follow as three separate records. Supported
        and exploratory options follow identically; the tier is recorded as the atlas's
        label for the fit, and no review or judgment is ever written here."""
        option_set_id, destination_id = body.get("option_set_id"), body.get("destination_id")
        from_page, follow_token = body.get("from_page"), body.get("follow_token")
        missing = [k for k in ("option_set_id", "destination_id", "from_page", "follow_token") if not body.get(k)]
        if missing:
            raise ApiError(f"missing {missing}")
        with _FOLLOW_LOCK:
            duplicate = Handlers._duplicate_follow(follow_token)
            if duplicate is not None:
                return duplicate
            option_set = _stored_option_set(option_set_id)
            if option_set is None:
                raise ApiError(f"unknown option set: {option_set_id}", status=404)
            option = next((o for o in option_set.get("options") or [] if o.get("destination_id") == destination_id), None)
            if option is None:
                raise ApiError(f"{destination_id!r} is not one of the options shown in {option_set_id}", status=409)

            field = _load_field(option_set.get("field") or fields_module.DEFAULT_FIELD)
            source_id, operator, policy = option_set.get("page_id"), option_set.get("operator"), option_set.get("policy")
            record = {"source_id": source_id, "selected_id": destination_id, "field": option_set.get("field"),
                      "policy": policy, "source_sha256": option_set.get("page_sha256"),
                      "destination_sha256": option.get("destination_sha256")}
            try:
                state.validate_movement(record, field=field, from_page=from_page,
                                        client_page=body.get("client_page"), runs_dir=None)
            except state.FollowValidationError as e:
                raise ApiError(str(e), status=409) from e
            _check_reader_is_on(field.id, from_page)

            described = {"tier": option.get("tier"), "tier_label": option.get("tier_label"),
                         "operator_fit": option.get("operator_fit"), "option_set_id": option_set_id,
                         "rank": option.get("rank"), "ordering_basis": body.get("ordering_basis") or option_set.get("ordering_basis")}
            shared = dict(
                proposal_kind="operator_option", field_id=field.id, source_id=source_id, destination_id=destination_id,
                policy=policy, operator=operator, relation_labels=None, run_dir=None, offer_set_id=None,
                follow_token=follow_token, source_sha256=record["source_sha256"],
                destination_sha256=record["destination_sha256"],
                extra={k: described[k] for k in ("tier", "operator_fit", "option_set_id")},
            )
            try:
                proposal_id = state.propose_offer(
                    offer_set_id=option_set_id, field=field.id, policy=policy, source_id=source_id,
                    source_sha256=record["source_sha256"], destination_id=destination_id,
                    destination_sha256=record["destination_sha256"],
                    destination_text=field.manifest[destination_id].text, data_dir=DATA_DIR,
                    kind="operator_option", operator=operator, extra=described,
                )
                _log_follow_events(stage="proposed", proposal_id=proposal_id, bond_id=None, **shared)
                bond_id = state.accept(proposal_id, data_dir=DATA_DIR)
                _log_follow_events(stage="accepted", proposal_id=proposal_id, bond_id=bond_id, **shared)
                new_state = state.follow(bond_id, data_dir=DATA_DIR, follow_token=follow_token)
                _log_follow_events(stage="followed", proposal_id=proposal_id, bond_id=bond_id, **shared)
            except state.StateError as e:
                raise ApiError(str(e)) from e
        return {"proposal_id": proposal_id, "bond_id": bond_id, "duplicate": False, "option_set_id": option_set_id,
                "operator": operator, "tier": option.get("tier"), "destination": destination_id, "reader_state": new_state}

    @staticmethod
    def get_fields(_query: dict) -> dict:
        return {
            "fields": [
                {"id": fields_module.FULL_41, "label": "Complete 41-page corpus (training + holdout)", "default": True},
                {"id": fields_module.HOLDOUT_21, "label": "21-page holdout field (London Fox / Princhetta)", "default": False},
            ],
            "policies": [
                {
                    "id": fields_module.DISCOVERY,
                    "label": "Discovery (excludes the immediate previous/next authored page)",
                    "default": True,
                },
                {
                    "id": fields_module.INCLUDE_ADJACENT,
                    "label": "Include adjacent pages (every other page eligible)",
                    "default": False,
                },
            ],
            "operators": relational_operators.OPERATOR_NAMES,
            "criteria": relational_operators.CRITERIA,
            "operator_version": relational_operators.VERSION,
            "criteria_versions": relational_operators.CRITERIA_BY_VERSION,
            "default_criteria_version": relational_operators.DEFAULT_VERSION,
            "outcome_states": {"operator": list(outcomes.OPERATOR_STATES), "offers": list(outcomes.OFFER_STATES)},
        }

    @staticmethod
    def get_field_status(query: dict) -> dict:
        field_id = query.get("field", [fields_module.DEFAULT_FIELD])[0]
        if field_id == fields_module.FULL_41:
            problems = fields_module.check_full_field_completeness()
        else:
            problems = []  # the holdout loader already raises on any incompleteness
        return {"field": field_id, "problems": problems, "ok": not problems}

    @staticmethod
    def get_pages(query: dict) -> dict:
        field_id = query.get("field", [fields_module.DEFAULT_FIELD])[0]
        field = _load_field(field_id)
        return {"field": field.id, "label": field.label, "pages": field.all_ids(), "groups": field.grouped_ids()}

    @staticmethod
    def get_page(query: dict) -> dict:
        field_id = query.get("field", [fields_module.DEFAULT_FIELD])[0]
        page_id = query.get("id", [None])[0]
        if not page_id:
            raise ApiError("missing 'id'")
        field = _load_field(field_id)
        if page_id not in field.manifest:
            raise ApiError(f"page {page_id!r} not in field {field.id!r}", status=404)
        page = field.manifest[page_id]
        neighbors = field.neighbors_of(page_id)
        return {
            "field": field.id, "id": page.id, "title": _title_of(page.id), "text": page.text, "sha256": page.sha256,
            "previous_id": neighbors["previous"], "next_id": neighbors["next"],
        }

    @staticmethod
    def get_saved_result(query: dict) -> dict:
        """Read-only lookup of a matching recorded run. Appends one passive
        `operator_result` session event (as it always has); never dispatches."""
        field_id = query.get("field", [fields_module.DEFAULT_FIELD])[0]
        source_id = query.get("source", [None])[0]
        operator = query.get("operator", [None])[0]
        policy = query.get("policy", [fields_module.DEFAULT_POLICY])[0]
        version = query.get("version", [relational_operators.DEFAULT_VERSION])[0]
        if not source_id or not operator:
            raise ApiError("missing 'source' or 'operator'")
        operator = operator.upper()
        try:
            field = fields_module.load_field(field_id)
            fields_module.validate_source_and_candidates(field, source_id, policy)
        except FieldError as e:
            raise ApiError(str(e)) from e
        if version not in relational_operators.CRITERIA_BY_VERSION:
            raise ApiError(f"unknown criteria version: {version!r}")
        criteria = relational_operators.CRITERIA_BY_VERSION[version]
        if operator not in criteria:
            raise ApiError(f"unknown operator: {operator!r}")

        criterion = criteria[operator]
        cfg = load_config()
        saved = saved_runs.find_matching_recorded_result(
            field, source_id, operator, criterion, expected_model=cfg.model, policy=policy, runs_dir=RUNS_DIR
        )
        record = _saved_result_to_dict(saved)
        record.update({
            "policy": policy, "criteria_version": version, "page_sha256": field.manifest[source_id].sha256,
            "candidate_count": len(field.eligible_candidate_ids(source_id, policy)),
        })
        if saved:
            record["message"] = outcomes.describe_operator_outcome({
                **record, "destination": record["selected_id"], "page_id": source_id,
            })
        _log_operator_result(
            "recorded" if saved else "none", field_id, source_id, operator,
            {"run_dir": record.get("run_dir"), "result": record if saved else None},
            policy=policy, criteria_version=version, page_sha256=record["page_sha256"],
        )
        return record

    @staticmethod
    def get_outcomes(query: dict) -> dict:
        """Every persisted outcome for a page (+operator), newest first, plus matching
        historical run dirs as read-only `source: "recorded"` views. Never dispatches."""
        field_id = query.get("field", [fields_module.DEFAULT_FIELD])[0]
        page_id = query.get("page", [None])[0] or query.get("source", [None])[0]
        operator = query.get("operator", [None])[0]
        policy = query.get("policy", [fields_module.DEFAULT_POLICY])[0]
        version = query.get("version", [relational_operators.DEFAULT_VERSION])[0]
        kind = query.get("kind", [outcomes.KIND_OPERATOR if operator else outcomes.KIND_OFFERS])[0]
        if not page_id:
            raise ApiError("missing 'page'")
        if kind not in outcomes.KINDS:
            raise ApiError(f"unknown outcome kind: {kind!r}")
        rows = outcomes.outcomes_for(
            kind=kind, field=field_id, page_id=page_id, operator=operator.upper() if operator else None,
            policy=policy, criteria_version=version if kind == outcomes.KIND_OPERATOR else None,
            runs_dir=RUNS_DIR, path=_outcomes_path(),
        )
        describe = outcomes.describe_operator_outcome if kind == outcomes.KIND_OPERATOR else None
        for row in rows:
            if "message" not in row and describe is not None:
                row["message"] = describe(row)
        return {"field": field_id, "page": page_id, "operator": operator, "policy": policy, "kind": kind,
                "criteria_version": version, "count": len(rows), "outcomes": rows}

    @staticmethod
    def post_request_selection(body: dict) -> dict:
        field_id = body.get("field", fields_module.DEFAULT_FIELD)
        source_id = body.get("source")
        operator = body.get("operator")
        policy = body.get("policy", fields_module.DEFAULT_POLICY)
        version = body.get("version", relational_operators.DEFAULT_VERSION)
        request_id = _new_request_id(body)
        if not source_id or not operator:
            raise ApiError("missing 'source' or 'operator'", payload={"request_id": request_id})
        operator = operator.upper()

        scope = (outcomes.KIND_OPERATOR, field_id, source_id, operator)
        key = (outcomes.KIND_OPERATOR, field_id, source_id, operator, policy, version)
        _register_latest(scope, request_id)

        def work(flight: _Flight) -> dict:
            base = {
                "kind": outcomes.KIND_OPERATOR, "field": field_id, "page_id": source_id, "operator": operator,
                "policy": policy, "criteria_version": version, "page_sha256": None, "run_dir": None,
                "destination": None, "confidence": None, "candidate_count": None, "error": None,
            }

            def finish(state_id: str, record: dict, *, status: int | None = None, **fields) -> dict:
                request_ids = FLIGHTS.close(key, flight)  # no more joiners: the outcome lists them all
                applicable, reason = _applicability(scope, request_ids, field_id, source_id)
                outcome = {**base, **fields, "state": state_id, "request_id": request_ids[0],
                           "request_ids": request_ids, "applicable": applicable, "not_applicable_reason": reason}
                outcome["message"] = outcomes.describe_operator_outcome(outcome)
                outcome = outcomes.append_outcome(_outcomes_path(), **outcome)
                payload = {
                    **record, "state": state_id, "message": outcome["message"], "outcome_id": outcome["outcome_id"],
                    "outcome": outcome, "policy": policy, "criteria_version": version,
                    "page_sha256": outcome["page_sha256"], "candidate_count": outcome["candidate_count"],
                    "leader_request_id": request_ids[0], "request_ids": request_ids,
                    "applicable": applicable, "not_applicable_reason": reason,
                }
                if status is not None:
                    raise ApiError(outcome["error"] or "request failed", status=status, payload=payload)
                return payload

            empty = {"run_id": None, "run_dir": None, "field": field_id, "source": source_id,
                     "operator": operator, "result": None, "kind": "new"}
            try:
                try:
                    field = fields_module.load_field(field_id)
                    if source_id not in field.manifest:
                        raise FieldError(f"source {source_id!r} is not eligible in field {field.id!r}")
                    base["page_sha256"] = field.manifest[source_id].sha256
                    candidates = field.eligible_candidate_ids(source_id, policy)
                    base["candidate_count"] = len(candidates)
                    if not candidates:
                        # Eligibility left nothing to choose from: Jev is never asked.
                        return finish(outcomes.NO_CANDIDATES, empty)
                    packet = reader_context.assemble_reader_packet(
                        field, source_id, operator, policy=policy, criteria_version=version)
                except (FieldError, CaseError, ValueError) as e:
                    return finish(outcomes.ERROR, {**empty, "error": str(e)}, status=400, error=str(e))

                cfg = load_config()
                if not cfg.has_live_credentials:
                    message = "TYPESAFE_API_KEY is not configured; cannot make a live request"
                    return finish(outcomes.ERROR, {**empty, "error": message}, status=503, error=message)

                _wait_for_free_run_slot(packet.case_id)
                outcome = run_case(packet, cfg, mock=False, corpus_hashes=_field_manifest_hashes(field), runs_dir=RUNS_DIR)
                run_dir = outcome["run_dir"]
                record = _run_outcome_to_dict(run_dir)
                if not outcome["ok"]:
                    record["error"] = outcome["error"]
                _log_operator_result(
                    "new", field_id, source_id, operator, record,
                    policy=policy, criteria_version=version, page_sha256=base["page_sha256"],
                    request_id=flight.request_ids[0],
                )
                result = record.get("result")
                if result is None:
                    return finish(outcomes.ERROR, record, run_dir=str(run_dir),
                                  error=record.get("error") or "the run produced no validated result")
                state_id = outcomes.ABSTAINED if result.get("is_abstention") else outcomes.SELECTED
                return finish(state_id, record, run_dir=str(run_dir), destination=result.get("selected_id"),
                              confidence=result.get("confidence"), mode="live" if record.get("live") else "mock",
                              returned_model=record.get("returned_model"))
            except ApiError:
                raise
            except Exception as e:  # noqa: BLE001 -- a server-side exception is still a recorded outcome
                message = f"{type(e).__name__}: {e}"
                return finish(outcomes.ERROR, {**empty, "error": message}, status=500, error=message)

        return Handlers._fly(key, request_id, work)

    @staticmethod
    def _fly(key: tuple, request_id: str, work) -> dict:
        try:
            payload, joined = FLIGHTS.run(key, request_id, work)
        except ApiError as e:
            leader = e.payload.get("leader_request_id", request_id)
            e.payload = {**e.payload, "request_id": request_id, "joined": request_id != leader}
            raise
        payload["request_id"] = request_id
        payload["joined"] = joined
        return payload

    @staticmethod
    def post_offers(body: dict) -> dict:
        """One offer hand for the page the reader is on. The only other endpoint that may
        dispatch provider work; a contextual cache miss is assessed inside this request."""
        field_id = body.get("field", fields_module.DEFAULT_FIELD)
        page_id = body.get("page") or body.get("source")
        policy = body.get("policy", fields_module.DEFAULT_POLICY)
        intention = body.get("intention")
        intention = str(intention).strip() or None if intention is not None else None
        request_id = _new_request_id(body)
        if not page_id:
            raise ApiError("missing 'page'", payload={"request_id": request_id})
        if policy not in fields_module.KNOWN_POLICIES:
            raise ApiError(f"unknown candidate policy: {policy!r}", payload={"request_id": request_id})
        field = _load_field(field_id)
        if page_id not in field.manifest:
            raise ApiError(f"page {page_id!r} not in field {field.id!r}", status=404, payload={"request_id": request_id})

        scope = (outcomes.KIND_OFFERS, field_id, page_id, None)
        key = (outcomes.KIND_OFFERS, field_id, page_id, intention, policy, None)
        _register_latest(scope, request_id)

        def work(flight: _Flight) -> dict:
            page_sha256 = field.manifest[page_id].sha256

            def persist(result: dict, *, error: str | None = None) -> tuple[dict, dict]:
                request_ids = FLIGHTS.close(key, flight)
                applicable, reason = _applicability(scope, request_ids, field_id, page_id)
                outcome = outcomes.append_outcome(
                    _outcomes_path(), kind=outcomes.KIND_OFFERS, state=result["state"], field=field_id,
                    page_id=page_id, page_sha256=page_sha256, operator=None, policy=policy, criteria_version=None,
                    offer_set_id=result.get("offer_set_id"), mode=result.get("mode"),
                    destinations=[o.get("destination_id") for o in result.get("offers") or []],
                    assessed_count=len(result.get("assessed_ids") or []),
                    not_assessed_count=result.get("not_assessed_count"), usage=result.get("usage"),
                    error=error, request_id=request_ids[0], request_ids=request_ids, applicable=applicable,
                    not_applicable_reason=reason, message=outcomes.describe_offer_outcome(result),
                )
                _append_offer_set(result, request_ids=request_ids, outcome_id=outcome["outcome_id"])
                session_log.append_event(
                    "offers_result", log_path=SESSION_LOG_PATH, field=field_id, page_id=page_id,
                    page_sha256=page_sha256, policy=policy, request_id=request_ids[0], state=result["state"],
                    offer_set_id=result.get("offer_set_id"),
                    destinations=[o.get("destination_id") for o in result.get("offers") or []],
                )
                view = _offer_view(result, field=field)
                view.update({"outcome_id": outcome["outcome_id"], "leader_request_id": request_ids[0],
                             "request_ids": request_ids, "applicable": applicable, "not_applicable_reason": reason})
                return view, outcome

            def fail(message: str, status: int, extra: dict | None = None) -> dict:
                result = {
                    "schema": "offer-result/1", "offer_set_id": f"offers_error_{uuid.uuid4().hex[:12]}",
                    "at": datetime.now(timezone.utc).isoformat(), "field": field_id, "page_id": page_id,
                    "page_sha256": page_sha256, "policy": policy, "mode": None, "state": outcomes.ERROR,
                    "offers": [], "shortlist": [], "assessed_ids": [], "not_assessed_count": 0,
                    "errors": [message], "synthesized_by": "reader-server",
                }
                view, _ = persist(result, error=message)
                raise ApiError(message, status=status, payload={**view, **(extra or {})})

            # The memory packet is built from the session log, so the log must say the reader
            # is ON this page. Otherwise: 409, persisted, and nothing is dispatched.
            conflict = _position_conflict(field_id, page_id, "requested")
            if conflict is not None:
                return fail(conflict[0], 409, extra=conflict[1])

            try:
                dispatch, mode, requested_model = OFFER_DISPATCH_FACTORY()
                events = session_log.read_events_with_seq(SESSION_LOG_PATH)
                result = OFFERS_BUILDER(
                    field, page_id, events, policy=policy, dispatch=dispatch, mode=mode,
                    requested_model=requested_model, intention=intention,
                )
            except ApiError as e:
                return fail(str(e), e.status)
            except Exception as e:  # noqa: BLE001 -- recorded as an error outcome, never a crash
                return fail(f"{type(e).__name__}: {e}", 500)

            got = result.get("state") if isinstance(result, dict) else None
            if got not in outcomes.PERSISTED_OFFER_STATES:
                return fail(f"the offers builder returned an unusable result (state={got!r})", 500)
            result = dict(result)
            result.setdefault("offer_set_id", f"offers_{uuid.uuid4().hex[:12]}")
            result.setdefault("at", datetime.now(timezone.utc).isoformat())
            for k, v in (("field", field_id), ("page_id", page_id), ("page_sha256", page_sha256), ("policy", policy)):
                result.setdefault(k, v)
            error = None
            if result["state"] == outcomes.ERROR:
                error = "; ".join(outcomes.error_text(e) for e in result.get("errors") or []) or result.get("state_detail") or "error"
            view, _ = persist(result, error=error)
            return view

        return Handlers._fly(key, request_id, work)

    @staticmethod
    def get_offers_latest(query: dict) -> dict:
        """The most recently persisted offer hand for this page+policy, for display after
        a refresh. Read-only: never builds, assesses, or dispatches anything."""
        field_id = query.get("field", [fields_module.DEFAULT_FIELD])[0]
        page_id = query.get("page", [None])[0]
        policy = query.get("policy", [fields_module.DEFAULT_POLICY])[0]
        if not page_id:
            raise ApiError("missing 'page'")
        matching = [
            r for r in _read_offer_sets()
            if r["result"].get("field") == field_id and r["result"].get("page_id") == page_id
            and r["result"].get("policy") == policy
        ]
        if not matching:
            return {"found": False, "state": outcomes.NOT_REQUESTED, "field": field_id, "page_id": page_id,
                    "policy": policy, "earlier_count": 0}
        latest = matching[-1]
        view = _offer_view(latest["result"])
        view.update({"found": True, "from_store": True, "outcome_id": latest.get("outcome_id"),
                     "request_ids": latest.get("request_ids"), "earlier_count": len(matching) - 1})
        return view

    @staticmethod
    def get_atlas_profiles(query: dict) -> dict:
        """The active page's 40 base pair profiles, read-only. An unassessed pair is a row
        with no scores -- never a zero."""
        source_id = query.get("source", [None])[0]
        mode = query.get("mode", ["live"])[0]
        if not source_id:
            raise ApiError("missing 'source'")
        if mode not in ("live", "mock"):
            raise ApiError(f"unknown atlas mode: {mode!r} (live or mock)")
        try:
            rows = PROFILES_PROVIDER(source_id, mode)
        except ImportError as e:
            return {"available": False, "source": source_id, "mode": mode, "rows": [], "dimensions": list(ATLAS_DIMENSIONS),
                    "counts": {}, "message": f"The relationship atlas is not installed in this checkout ({e})."}
        except ApiError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ApiError(f"atlas profiles unavailable: {type(e).__name__}: {e}", status=400) from e

        counts = {"complete": 0, "failed": 0, "stale": 0, "unassessed": 0}
        view_rows = []
        for row in rows:
            status = row.get("status") or "unassessed"
            counts[status] = counts.get(status, 0) + 1
            dims = row.get("dimensions") if status == "complete" and isinstance(row.get("dimensions"), dict) else None
            scores = {}
            for dim in ATLAS_DIMENSIONS:
                value = dims.get(dim) if dims else None
                if isinstance(value, dict):
                    value = value.get("score")
                scores[dim] = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            view_rows.append({
                "destination_id": row.get("destination_id"), "status": status,
                "is_authored_neighbor": bool(row.get("is_authored_neighbor")),
                "neighbor_relation": row.get("neighbor_relation"), "scores": scores,
                "returned_model": row.get("returned_model"), "assessment_id": row.get("assessment_id"),
                "stale_reasons": row.get("stale_reasons") or [], "last_errors": row.get("last_errors") or [],
            })
        return {"available": True, "source": source_id, "mode": mode, "total": len(view_rows), "counts": counts,
                "dimensions": list(ATLAS_DIMENSIONS), "rows": view_rows,
                "label": "LIVE assessments" if mode == "live" else "MOCK assessments (deterministic stand-in, not Jev)"}

    # --- propose / accept / follow: three separate steps, each validated ---

    @staticmethod
    def _run_dir_from(body: dict) -> Path:
        raw = body.get("run_dir") or ""
        if not raw:
            raise ApiError("missing 'run_dir'")
        run_dir = Path(raw)
        try:
            inside = Path(RUNS_DIR).resolve() in run_dir.resolve().parents
        except OSError:
            inside = False
        if not inside:
            raise ApiError(f"run_dir is not inside the recorded runs directory: {raw}", status=400)
        return run_dir

    @staticmethod
    def _validated_run_proposal(run_dir: Path, body: dict, *, require_from_page: bool) -> tuple[dict, object]:
        """Validate a run as a proposal BEFORE anything is recorded or moved."""
        try:
            preview = state.describe_run_proposal(run_dir)
        except state.StateError as e:
            raise ApiError(str(e), status=409) from e
        field = _load_field(preview.get("field") or body.get("field") or fields_module.DEFAULT_FIELD)
        from_page = body.get("from_page")
        if from_page is None and not require_from_page:
            from_page = preview["source_id"].split(".")[0]
        try:
            state.validate_movement(preview, field=field, from_page=from_page,
                                    client_page=body.get("client_page") or body.get("source"), runs_dir=RUNS_DIR)
        except state.FollowValidationError as e:
            raise ApiError(str(e), status=409) from e
        return preview, field

    @staticmethod
    def post_propose(body: dict) -> dict:
        """Step 1 of 3, on its own: validated, recorded, logged (`operator_proposed`).
        Never moves the reader."""
        run_dir = Handlers._run_dir_from(body)
        preview, field = Handlers._validated_run_proposal(run_dir, body, require_from_page=False)
        try:
            proposal_id = state.propose(run_dir, data_dir=DATA_DIR)
        except state.StateError as e:
            raise ApiError(str(e)) from e
        source_id, destination_id = preview["source_id"].split(".")[0], preview["selected_id"].split(".")[0]
        _log_follow_events(
            stage="proposed", proposal_kind="operator", field_id=field.id, source_id=source_id,
            destination_id=destination_id, policy=preview.get("policy"), operator=preview.get("operator"),
            relation_labels=None, run_dir=str(run_dir), offer_set_id=None, proposal_id=proposal_id, bond_id=None,
            follow_token=body.get("request_id"), source_sha256=field.manifest[source_id].sha256,
            destination_sha256=field.manifest[destination_id].sha256,
        )
        return {"proposal_id": proposal_id}

    @staticmethod
    def post_accept(body: dict) -> dict:
        """Step 2 of 3, on its own: recorded and logged (`offer_accepted`). Never moves the
        reader; the follow-time gate still runs when the bond is followed."""
        proposal_id = body.get("proposal_id")
        if not proposal_id:
            raise ApiError("missing 'proposal_id'")
        try:
            bond_id = state.accept(proposal_id, data_dir=DATA_DIR)
        except state.StateError as e:
            raise ApiError(str(e)) from e
        proposal = state.get_proposal(proposal_id, data_dir=DATA_DIR) or {}
        is_offer = proposal.get("kind") == "offer"
        _log_follow_events(
            stage="accepted", proposal_kind="offer" if is_offer else "operator", field_id=proposal.get("field"),
            source_id=proposal.get("source_id"), destination_id=proposal.get("selected_id"),
            policy=proposal.get("policy"), operator=None if is_offer else proposal.get("operator"),
            relation_labels=proposal.get("relation_labels") if is_offer else None, run_dir=proposal.get("run_dir"),
            offer_set_id=proposal.get("offer_set_id"), proposal_id=proposal_id, bond_id=bond_id,
            follow_token=body.get("request_id"), source_sha256=proposal.get("source_sha256"), destination_sha256=None,
        )
        return {"bond_id": bond_id}

    @staticmethod
    def post_follow(body: dict) -> dict:
        """Follow an already-accepted bond. Same guard as accept-and-follow: `from_page` is
        REQUIRED and must be the bond's source and the reader's last logged page; both
        endpoint versions and eligibility are validated; the traversal is idempotent per
        `follow_token` (when absent, a stable token derived from the bond id, so a replay of
        the same bond is a duplicate -- never a second traversal); and the same
        q_traversal / page_viewed events are logged so the log and reader_state agree."""
        bond_id = body.get("bond_id")
        if not bond_id:
            raise ApiError("missing 'bond_id'")
        from_page = body.get("from_page")
        if not from_page:
            raise ApiError("missing 'from_page': the page this route is being followed from")
        follow_token = body.get("follow_token") or f"bond:{bond_id}"
        with _FOLLOW_LOCK:
            bond = state.get_bond(bond_id, data_dir=DATA_DIR)
            if bond is None:
                raise ApiError(f"unknown bond: {bond_id}")
            duplicate = Handlers._duplicate_follow(follow_token)
            if duplicate is not None:
                return {**duplicate["reader_state"], "duplicate": True, "bond_id": bond_id}
            field = _load_field(bond.get("field") or body.get("field") or fields_module.DEFAULT_FIELD)
            try:
                state.validate_movement(bond, field=field, from_page=from_page,
                                        client_page=body.get("client_page"), runs_dir=RUNS_DIR)
            except state.FollowValidationError as e:
                raise ApiError(str(e), status=409) from e
            _check_reader_is_on(field.id, from_page)
            is_offer = bond.get("kind") == "offer" or (bond.get("kind") is None and bool(bond.get("offer_set_id")))
            if is_offer:
                stored = next((r for r in reversed(_read_offer_sets()) if r.get("offer_set_id") == bond.get("offer_set_id")), None)
                if stored is None or _memory_currency(stored["result"], field)[0] is False:
                    raise ApiError("this bond came from a hand computed for an earlier reading history (or an unknown "
                                   "hand); nothing was followed", status=409)
            source_id, destination_id = bond["source_id"].split(".")[0], bond["target_id"].split(".")[0]
            try:
                new_state = state.follow(bond_id, data_dir=DATA_DIR, follow_token=follow_token)
            except state.StateError as e:
                raise ApiError(str(e)) from e
            _log_follow_events(
                stage="followed", proposal_kind="offer" if is_offer else (bond.get("kind") or "operator"), field_id=field.id,
                extra={k: bond[k] for k in ("tier", "operator_fit", "option_set_id") if bond.get(k) is not None},
                source_id=source_id, destination_id=destination_id, policy=bond.get("policy"),
                operator=None if is_offer else bond.get("operator"),
                relation_labels=bond.get("relation_labels") if is_offer else None, run_dir=bond.get("run_dir"),
                offer_set_id=bond.get("offer_set_id"), proposal_id=bond.get("proposal_id"), bond_id=bond_id,
                follow_token=follow_token, source_sha256=field.manifest[source_id].sha256,
                destination_sha256=field.manifest[destination_id].sha256,
            )
        return {**new_state, "duplicate": False, "bond_id": bond_id}

    @staticmethod
    def _duplicate_follow(follow_token: str | None) -> dict | None:
        earlier = state.find_follow(follow_token, data_dir=DATA_DIR)
        if earlier is None:
            return None
        bond = state.get_bond(earlier["bond_id"], data_dir=DATA_DIR) or {}
        return {"proposal_id": bond.get("proposal_id"), "bond_id": earlier["bond_id"], "duplicate": True,
                "destination": earlier.get("to_id"), "reader_state": state.reader_state(data_dir=DATA_DIR)}

    @staticmethod
    def post_accept_and_follow(body: dict) -> dict:
        """Convenience action combining propose -> accept -> follow. Each step is still
        recorded through the same, separate state.py functions and files as if invoked
        individually -- this is one button, not one merged record. Validated first; a
        failed validation is a 409 and records/moves nothing."""
        run_dir = Handlers._run_dir_from(body)
        follow_token = body.get("follow_token")
        if not body.get("from_page"):
            raise ApiError("missing 'from_page': the page this route is being followed from")
        with _FOLLOW_LOCK:
            duplicate = Handlers._duplicate_follow(follow_token)
            if duplicate is not None:
                return duplicate
            preview, field = Handlers._validated_run_proposal(run_dir, body, require_from_page=True)
            source_id, destination_id = preview["source_id"], preview["selected_id"]
            _check_reader_is_on(field.id, body["from_page"])
            shared = dict(
                proposal_kind="operator", field_id=field.id, source_id=source_id, destination_id=destination_id,
                policy=preview.get("policy"), operator=preview.get("operator") or body.get("operator"),
                relation_labels=None, run_dir=str(run_dir), offer_set_id=None, follow_token=follow_token,
                source_sha256=field.manifest[source_id].sha256, destination_sha256=field.manifest[destination_id].sha256,
            )
            try:
                proposal_id = state.propose(run_dir, data_dir=DATA_DIR)
                _log_follow_events(stage="proposed", proposal_id=proposal_id, bond_id=None, **shared)
                bond_id = state.accept(proposal_id, data_dir=DATA_DIR)
                _log_follow_events(stage="accepted", proposal_id=proposal_id, bond_id=bond_id, **shared)
                new_state = state.follow(bond_id, data_dir=DATA_DIR, follow_token=follow_token)
                _log_follow_events(stage="followed", proposal_id=proposal_id, bond_id=bond_id, **shared)
            except state.StateError as e:
                raise ApiError(str(e)) from e
        return {"proposal_id": proposal_id, "bond_id": bond_id, "duplicate": False,
                "destination": destination_id, "reader_state": new_state}

    @staticmethod
    def post_follow_offer(body: dict) -> dict:
        """Follow one card of a persisted offer hand: validate, then propose -> accept ->
        follow as three separate records. The bond carries both endpoint hashes and the
        offer_set_id. Idempotent per follow_token."""
        offer_set_id = body.get("offer_set_id")
        destination_id = body.get("destination_id")
        from_page = body.get("from_page")
        follow_token = body.get("follow_token")
        missing = [k for k in ("offer_set_id", "destination_id", "from_page", "follow_token") if not body.get(k)]
        if missing:
            raise ApiError(f"missing {missing}")
        with _FOLLOW_LOCK:
            duplicate = Handlers._duplicate_follow(follow_token)
            if duplicate is not None:
                return duplicate
            stored = next((r for r in reversed(_read_offer_sets()) if r.get("offer_set_id") == offer_set_id), None)
            if stored is None:
                raise ApiError(f"unknown offer set: {offer_set_id}", status=404)
            result = stored["result"]
            if result.get("state") != outcomes.OFFERS:
                raise ApiError(f"offer set {offer_set_id} has state {result.get('state')!r}: there is nothing to follow", status=409)
            offer = next((o for o in result.get("offers") or [] if o.get("destination_id") == destination_id), None)
            if offer is None:
                raise ApiError(f"{destination_id!r} is not one of the routes offered in {offer_set_id}", status=409)

            field = _load_field(result.get("field") or fields_module.DEFAULT_FIELD)
            source_id = result.get("page_id")
            record = {
                "source_id": source_id, "selected_id": destination_id, "field": result.get("field"),
                "policy": result.get("policy"), "source_sha256": result.get("page_sha256"),
                "destination_sha256": offer.get("destination_sha256"),
            }
            try:
                state.validate_movement(record, field=field, from_page=from_page,
                                        client_page=body.get("client_page"), runs_dir=None)
            except state.FollowValidationError as e:
                raise ApiError(str(e), status=409) from e
            _check_reader_is_on(field.id, from_page)

            memory_current, current_sha = _memory_currency(result, field)
            if memory_current is False:
                message = ("this hand was computed for an earlier reading history, so it was not followed and you have "
                           "not moved \u2014 ask again for routes informed by how you got here this time")
                outcomes.append_outcome(
                    _outcomes_path(), kind=outcomes.KIND_OFFERS, state=outcomes.ERROR, event="follow_rejected",
                    field=field.id, page_id=source_id, page_sha256=result.get("page_sha256"), operator=None,
                    policy=result.get("policy"), criteria_version=None, offer_set_id=offer_set_id,
                    destination=destination_id, request_id=follow_token, error=message, message=message,
                    memory_sha256=result.get("memory_sha256"), current_memory_sha256=current_sha,
                )
                raise ApiError(message, status=409, payload={"memory_current": False, "current_memory_sha256": current_sha})

            labels = list(offer.get("relation_labels") or [])
            shared = dict(
                proposal_kind="offer", field_id=field.id, source_id=source_id, destination_id=destination_id,
                # An offered route was never an operator request: operator stays null and the
                # supported relation labels travel as their own field.
                policy=result.get("policy"), operator=None, relation_labels=labels,
                run_dir=None, offer_set_id=offer_set_id, follow_token=follow_token,
                source_sha256=record["source_sha256"], destination_sha256=record["destination_sha256"],
            )
            try:
                proposal_id = state.propose_offer(
                    offer_set_id=offer_set_id, field=field.id, policy=result.get("policy"), source_id=source_id,
                    source_sha256=record["source_sha256"], destination_id=destination_id,
                    destination_sha256=record["destination_sha256"],
                    destination_text=field.manifest[destination_id].text, relation_labels=labels, data_dir=DATA_DIR,
                )
                _log_follow_events(stage="proposed", proposal_id=proposal_id, bond_id=None, **shared)
                bond_id = state.accept(proposal_id, data_dir=DATA_DIR)
                _log_follow_events(stage="accepted", proposal_id=proposal_id, bond_id=bond_id, **shared)
                new_state = state.follow(bond_id, data_dir=DATA_DIR, follow_token=follow_token)
                _log_follow_events(stage="followed", proposal_id=proposal_id, bond_id=bond_id, **shared)
            except state.StateError as e:
                raise ApiError(str(e)) from e
        return {"proposal_id": proposal_id, "bond_id": bond_id, "duplicate": False, "offer_set_id": offer_set_id,
                "destination": destination_id, "reader_state": new_state}

    @staticmethod
    def post_preserve(body: dict) -> dict:
        bond_id = body.get("bond_id")
        if not bond_id:
            raise ApiError("missing 'bond_id'")
        try:
            entry_id = state.preserve(bond_id, data_dir=DATA_DIR)
        except state.StateError as e:
            raise ApiError(str(e)) from e
        session_log.append_event("preserved", log_path=SESSION_LOG_PATH, bond_id=bond_id, entry_id=entry_id)
        return {"entry_id": entry_id}

    @staticmethod
    def get_reader_state(_query: dict) -> dict:
        """Recorded Q position/history, plus `last_viewed` (computed from the session
        log, never stored) so a refresh can return to the page actually being read."""
        result = dict(state.reader_state(data_dir=DATA_DIR))
        last = session_log.last_encounter(SESSION_LOG_PATH)
        result["last_viewed"] = (
            {"field": last.get("field"), "page_id": last.get("page_id"), "seq": last.get("seq")} if last else None
        )
        # The operator list the reader last opened on the page they are STILL on, so a
        # reload can show it again (a GET; never a dispatch). Computed, never stored.
        result["last_operator_options"] = None
        if last:
            for event in reversed(session_log.read_events(SESSION_LOG_PATH)):
                if event.get("event") in ("page_viewed", "back") and event.get("page_id") != last.get("page_id"):
                    break
                if event.get("event") == "operator_options_shown" and event.get("page_id") == last.get("page_id") \
                        and event.get("field") == last.get("field"):
                    result["last_operator_options"] = {k: event.get(k) for k in ("field", "page_id", "operator", "policy")}
                    break
        return result

    @staticmethod
    def post_review(body: dict) -> dict:
        run_dir = Handlers._run_dir_from(body)  # rejects empty/missing and anything outside RUNS_DIR
        if not (run_dir / "input.json").is_file():
            raise ApiError(f"not a recorded run: {run_dir.name}", status=404)
        try:
            review = update_review(
                run_dir,
                correspondence=body.get("correspondence"),
                reading_effect=body.get("reading_effect"),
                grounding_score=body.get("grounding_score"),
                effect_score=body.get("effect_score"),
                decision=body.get("decision"),
            )
        except ReviewError as e:
            raise ApiError(str(e)) from e
        return review

    @staticmethod
    def post_session_navigation(body: dict) -> dict:
        """Passive navigation logging only (page views, field switches, Back,
        Previous/Next, card previews). Requires no written notes and never touches Q/R
        state or the Gibsey Vault. `via` records provenance -- which control caused the
        navigation -- without affecting anything else. A Back is a NEW `back` event:
        nothing it walks back over is removed. The page hash is looked up here, from the
        manifest, never taken from the client."""
        event = body.get("event")
        if event not in ("page_viewed", "field_selected", "back", "offer_previewed"):
            raise ApiError(f"unknown navigation event: {event!r}")
        page_sha256 = None
        page_id = body.get("page_id")
        if page_id and body.get("field") in fields_module.KNOWN_FIELDS:
            try:
                page = fields_module.load_field(body["field"]).manifest.get(page_id)
                page_sha256 = page.sha256 if page is not None else None
            except FieldError:
                page_sha256 = None
        extra = {k: body[k] for k in ("policy", "request_id", "from_field", "destination_id", "offer_set_id") if body.get(k)}
        record = session_log.append_event(
            event,
            log_path=SESSION_LOG_PATH,
            field=body.get("field"),
            page_id=page_id,
            from_page=body.get("from_page"),
            via=body.get("via", "dropdown"),
            page_sha256=page_sha256,
            **extra,
        )
        return record

    # --- Core (v0.3): session, options, execute, status, journey ---

    @staticmethod
    def post_core_session(body: dict) -> dict:
        """Start or resume. A known `session_id` resumes (nothing written). Otherwise a new
        session starts at `page` (default: the page the reader was last recorded on) --
        the one `session_started` event, mirrored as a `page_viewed(via="start")`."""
        session_id = body.get("session_id") or None
        if session_id is not None and not isinstance(session_id, str):
            raise ApiError("session_id must be a string")
        via = body.get("via") if isinstance(body.get("via"), str) and body.get("via") else "start"
        via = via[:32]
        with _CORE_LOCK:
            try:
                if session_id and _session_events(session_id):
                    core = _core_for_session(session_id)
                    return _session_view(core, session_id, started=False, resumed=True)
                field = _load_field(body.get("field") or fields_module.DEFAULT_FIELD)
                page_id = body.get("page") or _reader_last_page(field)
                if page_id not in field.manifest:
                    raise ApiError(f"page {page_id!r} not in field {field.id!r}", status=404)
                core = _core(field)
                started = core.start_session(page_id, session_id=session_id or None, via=via)
                return _session_view(core, started["session_id"], started=True, resumed=False)
            except CoreError as e:
                raise _core_error(e) from e
            except journal.JournalError as e:
                raise ApiError(f"journal conflict: {e}", status=409, payload={"code": "journal_conflict"}) from e

    @staticmethod
    def get_core_session(query: dict) -> dict:
        session_id = query.get("session_id", [None])[0]
        if not session_id:
            raise ApiError("missing 'session_id'")
        try:
            return _session_view(_core_for_session(session_id), session_id, started=False, resumed=True)
        except CoreError as e:
            raise _core_error(e) from e

    @staticmethod
    def post_core_options(body: dict) -> dict:
        """The ordered bonds available at the session's current revision. Pure read of the
        saved atlas plus ONE non-bumping journal event (none at all when the same set was
        already resolved at this revision). Writes nothing to the session log, the
        outcomes file or the option-set file."""
        session_id, operator = body.get("session_id"), body.get("operator")
        policy = body.get("policy") or fields_module.DEFAULT_POLICY
        if not session_id or not operator:
            raise ApiError("missing 'session_id' or 'operator'")
        operator = str(operator).upper()
        if policy not in fields_module.KNOWN_POLICIES:
            raise ApiError(f"unknown candidate policy: {policy!r}")
        with _CORE_LOCK:
            try:
                core = _core_for_session(session_id)
                offer_set = core.resolve_options(session_id, operator, policy=policy)
                state_now = core.state(session_id)
            except CoreError as e:
                raise _core_error(e) from e
            except journal.JournalError as e:
                raise ApiError(f"journal conflict: {e}", status=409, payload={"code": "journal_conflict"}) from e
        view = _core_options_view(offer_set, core.field)
        view["session_id"] = session_id
        view["current_revision"] = state_now.r
        view["position"] = _position_advisory(core.field.id, state_now.page)
        return view

    @staticmethod
    def post_core_execute(body: dict) -> dict:
        """Follow one offered bond. Dedup first (identical retry -> the recorded result with
        `duplicate: true`), then the Core's own validation; a refusal is a 409 with
        {code, reason, details} and nothing moves. The commit is one journal append; the
        legacy mirrors are written after it by the projector."""
        session_id = body.get("session_id")
        missing = [k for k in ("session_id", "offer_set_id", "bond_version_id", "request_id") if not body.get(k)]
        if missing:
            raise ApiError(f"missing {missing}")
        expected = body.get("expected_revision")
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise ApiError("expected_revision must be an integer")
        with _CORE_LOCK:
            try:
                core = _core_for_session(session_id)
                result = core.execute_action(session_id, offer_set_id=str(body["offer_set_id"]),
                                             bond_version_id=str(body["bond_version_id"]), expected_revision=expected,
                                             request_id=str(body["request_id"]))
            except CoreError as e:
                error = _core_error(e)
                error.payload["current_revision"] = e.details.get("current_revision")
                if e.code in ("stale_revision", "paused", "unknown_or_stale_offer_set", "source_mismatch"):
                    try:  # so the client can show where the session actually is, without a second round trip
                        error.payload["session"] = _session_view(_core_for_session(session_id), session_id)
                    except (CoreError, ApiError):
                        pass
                raise error from e
            except journal.JournalError as e:
                raise ApiError(f"journal conflict: {e}", status=409, payload={"code": "journal_conflict"}) from e
            view = dict(result)
            view["session"] = _session_view(core, session_id)
        view["reader_state"] = state.reader_state(data_dir=DATA_DIR)
        view["position"] = view["session"]["position"]
        return view

    @staticmethod
    def get_core_status(query: dict) -> dict:
        session_id, request_id = query.get("session_id", [None])[0], query.get("request_id", [None])[0]
        if not session_id or not request_id:
            raise ApiError("missing 'session_id' or 'request_id'")
        try:
            return _core_for_session(session_id).get_action_status(session_id, request_id)
        except CoreError as e:
            raise _core_error(e) from e

    @staticmethod
    def post_core_pause(body: dict) -> dict:
        session_id = body.get("session_id")
        if not session_id:
            raise ApiError("missing 'session_id'")
        with _CORE_LOCK:
            try:
                core = _core_for_session(session_id)
                core.pause(session_id)
                return _session_view(core, session_id)
            except CoreError as e:
                raise _core_error(e) from e
            except journal.JournalError as e:
                raise ApiError(f"journal conflict: {e}", status=409, payload={"code": "journal_conflict"}) from e

    @staticmethod
    def post_core_resume(body: dict) -> dict:
        session_id = body.get("session_id")
        if not session_id:
            raise ApiError("missing 'session_id'")
        with _CORE_LOCK:
            try:
                core = _core_for_session(session_id)
                core.unpause(session_id)
                return _session_view(core, session_id)
            except CoreError as e:
                raise _core_error(e) from e
            except journal.JournalError as e:
                raise ApiError(f"journal conflict: {e}", status=409, payload={"code": "journal_conflict"}) from e

    @staticmethod
    def get_core_journey(query: dict) -> dict:
        """Read-only step-through of a recorded journey: every encounter with its exact
        prose (from the field manifest by version id; a version that is no longer current
        is said so and shows nothing), the offer set that produced it, the selection and
        the state before/after. Replays the journal with the pure reducer; writes nothing."""
        session_id = query.get("session_id", [None])[0]
        if not session_id:
            raise ApiError("missing 'session_id'")
        if not core_module.SESSION_ID_RE.match(session_id):
            raise ApiError(f"invalid session id {session_id!r}", payload={"code": "invalid_session"})
        events = _session_events(session_id)
        if not events:
            raise ApiError(f"no such session: {session_id}", status=404, payload={"code": "unknown_session"})
        field_id = events[0].get("field_id")
        field = _load_field(field_id if field_id in fields_module.KNOWN_FIELDS else fields_module.DEFAULT_FIELD)
        return _journey(session_id, events, field)


def _prose(field, page_id: str, version_id: str) -> dict:
    page = field.manifest.get(page_id)
    if page is None:
        return {"text": None, "current": False, "note": f"{page_id} is not in field {field.id}; nothing is shown"}
    if identity.version_id(page_id, page.sha256) != version_id:
        return {"text": None, "current": False, "sha256": None,
                "note": f"{version_id} is no longer the current text of {page_id} "
                        f"(now {identity.version_id(page_id, page.sha256)}); the exact prose of that version is not "
                        "in the manifest, so nothing is shown"}
    return {"text": page.text, "current": True, "sha256": page.sha256, "title": _title_of(page_id), "note": None}


def _journey(session_id: str, events: list[dict], field) -> dict:
    offer_sets: dict[str, dict] = {}
    rejections: list[dict] = []
    encounters: list[dict] = []
    before = reducer.State()
    atlas_config_ids: set[str] = set()
    for event in events:
        kind = event.get("event")
        after = reducer.apply(before, event)
        if kind == "offer_set_created":
            offer_sets[event["offer_set_id"]] = event
            if event.get("atlas_config_id"):
                atlas_config_ids.add(event["atlas_config_id"])
        elif kind == "action_rejected":
            rejections.append({k: event.get(k) for k in ("seq", "at", "request_id", "code", "reason", "offer_set_id",
                                                            "bond_version_id", "expected_revision", "revision_at_rejection")})
        elif kind in ("session_started", "action_committed"):
            entry = dict(after.H[-1])
            version_id = entry["version_id"]
            record = {
                **entry, "at": event.get("at"), "prose": _prose(field, entry["page_id"], version_id),
                "revision_after": after.r, "encounter_count_after": len(after.H),
                "count_for_version_after": after.c.get(version_id), "is_return": entry.get("previous_encounter_index") is not None,
                "action": None,
            }
            if kind == "action_committed":
                offer = offer_sets.get(event.get("offer_set_id")) or {}
                bonds = []
                for bond in offer.get("bonds") or []:
                    bonds.append({**bond, "selected": bond.get("bond_version_id") == event.get("bond_version_id"),
                                  "evidence_note": "decision evidence (model distribution) — no textual evidence span recorded"})
                record["action"] = {
                    "request_id": event.get("request_id"), "bond_version_id": event.get("bond_version_id"),
                    "operator": event.get("operator"), "wording": event.get("wording"), "tier": event.get("tier"),
                    "operator_fit": event.get("operator_fit"), "assessment_id": event.get("assessment_id"),
                    "expected_revision": event.get("expected_revision"), "fingerprint": event.get("fingerprint"),
                    "offer_set": None if not offer else {
                        "offer_set_id": offer.get("offer_set_id"), "revision": offer.get("revision"),
                        "operator": offer.get("operator"), "policy": offer.get("policy"),
                        "source_version": offer.get("source_version"), "source_page": offer.get("source_page"),
                        "atlas_config_id": offer.get("atlas_config_id"), "options_policy_version": offer.get("options_policy_version"),
                        "options_state": offer.get("options_state"), "counts": offer.get("counts"),
                        "exclusions": offer.get("exclusions"), "event_seq": offer.get("seq"), "at": offer.get("at"),
                        "bonds": bonds,
                    },
                    "offer_set_missing": not offer,
                    "state_before": {"revision": before.r, "encounter_count": len(before.H),
                                     "count_for_version": before.c.get(version_id, 0), "active_version": before.v},
                    "state_after": {"revision": after.r, "encounter_count": len(after.H),
                                    "count_for_version": after.c.get(version_id), "active_version": after.v},
                }
            encounters.append(record)
        before = after
    final = before
    return {
        "schema": "core-journey/1", "session_id": session_id, "field": field.id, "field_id": final.field_id,
        "atlas_config_ids": sorted(atlas_config_ids), "revision": final.r, "paused": final.paused,
        "encounter_count": len(final.H), "event_count": len(events), "last_seq": final.last_seq,
        "started_at": events[0].get("at"), "last_event_at": events[-1].get("at"),
        "encounters": encounters, "rejections": rejections, "state": final.canonical(),
        "evidence_note": "decision evidence (model distribution) — no textual evidence span recorded",
        "clock_note": "wall time is the journal's recorded `at`; encounter order is the arrival index; neither is synthetic timing",
    }


GET_ROUTES = {
    "/api/fields": Handlers.get_fields,
    "/api/field-status": Handlers.get_field_status,
    "/api/pages": Handlers.get_pages,
    "/api/page": Handlers.get_page,
    "/api/saved-result": Handlers.get_saved_result,
    "/api/reader-state": Handlers.get_reader_state,
    "/api/outcomes": Handlers.get_outcomes,
    "/api/offers/latest": Handlers.get_offers_latest,
    "/api/atlas/profiles": Handlers.get_atlas_profiles,
    "/api/operator-options": Handlers.get_operator_options,
    "/api/build": Handlers.get_build,
    "/api/core/session": Handlers.get_core_session,
    "/api/core/status": Handlers.get_core_status,
    "/api/core/journey": Handlers.get_core_journey,
}
POST_ROUTES = {
    "/api/core/session": Handlers.post_core_session,
    "/api/core/options": Handlers.post_core_options,
    "/api/core/execute": Handlers.post_core_execute,
    "/api/core/pause": Handlers.post_core_pause,
    "/api/core/resume": Handlers.post_core_resume,
    "/api/request-selection": Handlers.post_request_selection,
    "/api/offers": Handlers.post_offers,
    "/api/propose": Handlers.post_propose,
    "/api/accept": Handlers.post_accept,
    "/api/follow": Handlers.post_follow,
    "/api/accept-and-follow": Handlers.post_accept_and_follow,
    "/api/follow-offer": Handlers.post_follow_offer,
    "/api/refine-options": Handlers.post_refine_options,
    "/api/follow-option": Handlers.post_follow_option,
    "/api/preserve": Handlers.post_preserve,
    "/api/review": Handlers.post_review,
    "/api/session/navigation": Handlers.post_session_navigation,
}

_DEMO_MISSING_HTML = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'><title>PR2 memory demonstration</title></head>"
    "<body style='font-family: Georgia, serif; max-width: 640px; margin: 3rem auto; line-height: 1.6'>"
    "<h1>PR2 memory demonstration (fixtures)</h1>"
    "<p>Not generated yet. This page will show the fixture comparison once "
    "<code>gibsey pr2-demo</code> has been run. It is built from declared demonstration fixtures, "
    "never from the real reading session.</p><p><a href='/'>Back to the reader</a></p></body></html>"
)


class ReaderRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quieter default logging
        sys.stderr.write(f"[reader] {self.address_string()} {fmt % args}\n")

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file_under(self, root: Path, rel_path: str) -> None:
        root = Path(root).resolve()
        target = (root / rel_path).resolve()
        if root not in target.parents and target != root:
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        content_type, _ = mimetypes.guess_type(str(target))
        if content_type and (content_type.startswith("text/") or content_type == "application/json"):
            content_type += "; charset=utf-8"
        self._send_bytes(target.read_bytes(), content_type or "application/octet-stream")

    def _send_static(self, rel_path: str) -> None:
        self._send_file_under(STATIC_DIR, rel_path)

    def _send_demo(self, rel_path: str) -> None:
        """Static demonstration fixtures only; never reads or writes the real session."""
        if rel_path in ("", "comparison.html"):
            target = Path(DEMO_DIR) / "comparison.html"
            if not target.is_file():
                self._send_bytes(_DEMO_MISSING_HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            rel_path = "comparison.html"
        self._send_file_under(Path(DEMO_DIR), rel_path)

    def _send_api_error(self, e: ApiError) -> None:
        self._send_json({**e.payload, "error": str(e)}, status=e.status)

    def do_GET(self) -> None:  # noqa: N802 (stdlib method name)
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path in GET_ROUTES:
            try:
                result = GET_ROUTES[parsed.path](query)
                self._send_json(result)
            except ApiError as e:
                self._send_api_error(e)
            except Exception as e:  # noqa: BLE001 -- last-resort guard, never crash the server
                self._send_json({"error": f"{type(e).__name__}: {e}"}, status=500)
            return

        if parsed.path == "/":
            self._send_static("index.html")
        elif parsed.path in ("/journey", "/inspect/journey"):
            self._send_static("journey.html")  # read-only inspection page; it only ever GETs /api/core/journey
        elif parsed.path == "/demo/pr2" or parsed.path.startswith("/demo/pr2/"):
            self._send_demo(parsed.path[len("/demo/pr2"):].lstrip("/"))
        else:
            self._send_static(parsed.path.lstrip("/"))

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in POST_ROUTES:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON body"}, status=400)
            return
        if not isinstance(body, dict):
            self._send_json({"error": "the JSON body must be an object"}, status=400)
            return
        try:
            result = POST_ROUTES[parsed.path](body)
            self._send_json(result)
        except ApiError as e:
            self._send_api_error(e)
        except (JevError, ProviderResultError) as e:
            self._send_json({"error": str(e), "request_id": body.get("request_id")}, status=502)
        except Exception as e:  # noqa: BLE001
            self._send_json({"error": f"{type(e).__name__}: {e}", "request_id": body.get("request_id")}, status=500)


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("the reader app must bind to localhost only")
    server = ThreadingHTTPServer((host, port), ReaderRequestHandler)
    url = f"http://{host}:{port}/"
    print(f"Gibsey Lab reader running at {url} (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
