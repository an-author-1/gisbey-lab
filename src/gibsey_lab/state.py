"""Minimal explicit Q and R actions.

A Jev selection (a run's result.json) or an offered route is only a candidate bond
proposal. Nothing here runs automatically after `run-case` — propose / accept / follow /
preserve are separate, explicit steps, matching the QDPI distinction between discovery,
acceptance, traversal (Q), and preservation (R).

Guarantees:
- Proposing and accepting never move the reader; only `follow` does.
- New proposals and bonds record the field, candidate policy, and the sha256 of BOTH
  endpoints as they were when the proposal was made. Historical entries without those
  fields stay readable and are never rewritten; `validate_movement` checks them against
  the originating run's `corpus_hashes` instead.
- `validate_movement` is the follow-time gate: it raises `FollowValidationError` (and the
  caller moves nothing) unless the destination is in the field, is eligible under the
  policy recorded with the proposal, both endpoint versions still equal the current
  manifest, and the proposal's source page is the page the reader is actually on.
- `follow` records `from_page` as the bond's own source page -- never the stored
  `active_page`, which is stale whenever the reader navigated manually -- and is
  idempotent per `follow_token` (a duplicate click is one traversal, one history entry).

The reader's Gibsey Vault (data/gibsey_vault/) is distinct from the Obsidian source vault
(vault/): the former holds a reader's explicitly preserved selections, not authored source.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "data"

# Serializes every load-modify-save below (the reader runs a threading HTTP server).
_STATE_LOCK = threading.RLock()


# Descriptive fields an operator-option proposal carries through to its bond.
_OPTION_FIELDS = ("tier", "tier_label", "operator_fit", "option_set_id", "rank", "ordering_basis")


class StateError(Exception):
    pass


class FollowValidationError(StateError):
    """A proposal/bond that may not be followed right now. Nothing has been moved."""


def _load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(data_dir: Path) -> dict[str, Path]:
    return {
        "proposals": data_dir / "proposals.json",
        "bonds": data_dir / "bonds.json",
        "reader_state": data_dir / "reader_state.json",
        "vault_dir": data_dir / "gibsey_vault",
        "vault_index": data_dir / "gibsey_vault" / "index.json",
    }


def _page_of(passage_id: str | None) -> str | None:
    return passage_id.split(".")[0] if isinstance(passage_id, str) and passage_id else None


def describe_run_proposal(run_dir: Path) -> dict:
    """The proposal record `propose(run_dir)` would write -- without writing anything.
    Raises StateError for a run that can never be proposed (unreadable, failed/error,
    or an abstention). Lets a caller validate a proposal before it is recorded."""
    run_dir = Path(run_dir)
    try:
        input_record = json.loads((run_dir / "input.json").read_text())
        result = json.loads((run_dir / "result.json").read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise StateError(f"not a readable recorded run: {run_dir} ({type(e).__name__})") from e
    if not isinstance(input_record, dict) or "run_id" not in input_record:
        raise StateError(f"not a recorded run (no run_id): {run_dir}")
    if result is None:
        raise StateError("cannot propose from a run with no validated outcome (failed/error run)")
    if result.get("is_abstention"):
        raise StateError("cannot propose a bond: this run abstained (NONE) — there is no destination")

    run_id = input_record["run_id"]
    reader_state_at_run = input_record.get("reader_state") or {}
    corpus_hashes = input_record.get("corpus_hashes") or {}
    source_id = input_record["source_id"]
    selected_id = result["selected_id"]
    return {
        "proposal_id": f"prop_{run_id}",
        "kind": "operator",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "case_id": input_record["case_id"],
        "source_id": source_id,
        "active_id": input_record["active_id"],
        "selected_id": selected_id,
        "selected_text": result["selected_text"],
        "confidence": result["confidence"],
        "field": reader_state_at_run.get("field"),
        "policy": reader_state_at_run.get("policy"),
        "operator": reader_state_at_run.get("operator"),
        "criteria_version": reader_state_at_run.get("criteria_version"),
        "source_sha256": corpus_hashes.get(_page_of(source_id)),
        "destination_sha256": corpus_hashes.get(_page_of(selected_id)),
    }


def propose(run_dir: Path, *, data_dir: Path = DEFAULT_DATA_DIR) -> str:
    record = describe_run_proposal(run_dir)  # abstention/error runs stop here, before any write
    run_id = record["run_id"]
    with _STATE_LOCK:
        p = _paths(data_dir)
        proposals = _load(p["proposals"], {})
        if run_id in proposals:
            return proposals[run_id]["proposal_id"]  # repeat-safe: same run, same proposal
        proposals[run_id] = {**record, "status": "proposed", "created_at": _now()}
        _save(p["proposals"], proposals)
        return record["proposal_id"]


def propose_offer(
    *,
    offer_set_id: str,
    field: str,
    policy: str,
    source_id: str,
    source_sha256: str,
    destination_id: str,
    destination_sha256: str,
    destination_text: str,
    relation_labels: list[str] | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
    kind: str = "offer",
    operator: str | None = None,
    extra: dict | None = None,
) -> str:
    """Record one offered route as a proposal. Repeat-safe per (offer set, destination).
    An offer is evidence for a possible bond, never a bond: nothing moves here.

    `kind="operator_option"` records one row of a ranked operator option list instead
    (`offer_set_id` is then the option_set_id); `operator` and `extra` (tier,
    operator_fit, option_set_id) are stored on the proposal and copied to the bond. The
    tier is the atlas's label for the fit -- following an exploratory option is the
    reader's explicit choice and records no review or judgment of any kind."""
    if kind not in ("offer", "operator_option"):
        raise StateError(f"unknown proposal kind: {kind!r}")
    if not offer_set_id or not source_id or not destination_id:
        raise StateError("an offer proposal needs an offer_set_id, a source, and a destination")
    if not source_sha256 or not destination_sha256:
        raise StateError("an offer proposal must record the sha256 of both endpoints")
    key = f"{'offer' if kind == 'offer' else 'option'}:{offer_set_id}:{destination_id}"
    with _STATE_LOCK:
        p = _paths(data_dir)
        proposals = _load(p["proposals"], {})
        if key in proposals:
            return proposals[key]["proposal_id"]
        safe_set_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(offer_set_id))  # ids become vault file names
        proposal_id = f"prop_{safe_set_id}_{destination_id}"
        proposals[key] = {
            "proposal_id": proposal_id,
            "kind": kind,
            "run_id": None,
            "run_dir": None,
            "offer_set_id": offer_set_id if kind == "offer" else None,
            "case_id": None,
            "source_id": source_id,
            "active_id": None,
            "selected_id": destination_id,
            "selected_text": destination_text,
            "confidence": None,
            "relation_labels": list(relation_labels or []),
            "operator": operator,
            **{k: v for k, v in (extra or {}).items() if k in _OPTION_FIELDS},
            "field": field,
            "policy": policy,
            "source_sha256": source_sha256,
            "destination_sha256": destination_sha256,
            "status": "proposed",
            "created_at": _now(),
        }
        _save(p["proposals"], proposals)
        return proposal_id


def get_proposal(proposal_id: str, *, data_dir: Path = DEFAULT_DATA_DIR) -> dict | None:
    proposals = _load(_paths(data_dir)["proposals"], {})
    return next((v for v in proposals.values() if v["proposal_id"] == proposal_id), None)


def get_bond(bond_id: str, *, data_dir: Path = DEFAULT_DATA_DIR) -> dict | None:
    return _load(_paths(data_dir)["bonds"], {}).get(bond_id)


def _legacy_run_input(record: dict, runs_dir: Path | None) -> dict:
    """input.json of the run a legacy (hash-less, policy-less) proposal/bond came from."""
    candidates = []
    if record.get("run_dir"):
        candidates.append(Path(record["run_dir"]))
    run_id = record.get("run_id")
    if not run_id and isinstance(record.get("proposal_id"), str) and record["proposal_id"].startswith("prop_"):
        run_id = record["proposal_id"][len("prop_"):]
    if run_id and runs_dir is not None:
        candidates.append(Path(runs_dir) / run_id)
    for run_dir in candidates:
        try:
            loaded = json.loads((run_dir / "input.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(loaded, dict):
            return loaded
    return {}


def validate_movement(
    record: dict,
    *,
    field,
    from_page: str | None,
    client_page: str | None = None,
    runs_dir: Path | None = None,
) -> None:
    """Follow-time gate for a proposal or bond dict. `field` is a gibsey_lab.fields.Field
    (anything with `.id`, `.manifest[pid].sha256`, `.eligible_candidate_ids(src, policy)`).
    Raises FollowValidationError and changes nothing on any failure."""
    source_id = _page_of(record.get("source_id"))
    destination_id = _page_of(record.get("selected_id") or record.get("target_id"))
    if not source_id or not destination_id:
        raise FollowValidationError("this proposal has no source or no destination")

    recorded_field = record.get("field")
    if recorded_field and recorded_field != field.id:
        raise FollowValidationError(
            f"this proposal was made in field {recorded_field!r}, not the current field {field.id!r}"
        )
    if destination_id not in field.manifest:
        raise FollowValidationError(f"destination {destination_id!r} is not a page in field {field.id!r}")
    if source_id not in field.manifest:
        raise FollowValidationError(f"source {source_id!r} is not a page in field {field.id!r}")

    for label, value in (("from_page", from_page), ("the page the reader reports being on", client_page)):
        if value is not None and value != source_id:
            raise FollowValidationError(
                f"this route starts from {source_id!r}, but {label} is {value!r}; nothing was followed"
            )
    if from_page is None:
        raise FollowValidationError("missing from_page: cannot confirm which page this route is being followed from")

    legacy_input: dict | None = None
    policy = record.get("policy")
    if not policy:
        legacy_input = _legacy_run_input(record, runs_dir)
        # Runs recorded before candidate policies existed offered every other page.
        policy = (legacy_input.get("reader_state") or {}).get("policy") or "include-adjacent"
    try:
        eligible = field.eligible_candidate_ids(source_id, policy)
    except Exception as e:  # noqa: BLE001 -- an unknown recorded policy is a validation failure, not a crash
        raise FollowValidationError(f"cannot check eligibility under recorded policy {policy!r}: {e}") from e
    if destination_id not in eligible:
        raise FollowValidationError(
            f"destination {destination_id!r} is not eligible from {source_id!r} under the recorded "
            f"candidate policy {policy!r}"
        )

    source_hash = record.get("source_sha256")
    destination_hash = record.get("destination_sha256")
    if not source_hash or not destination_hash:
        if legacy_input is None:
            legacy_input = _legacy_run_input(record, runs_dir)
        legacy = legacy_input.get("corpus_hashes") or {}
        source_hash = source_hash or legacy.get(source_id)
        destination_hash = destination_hash or legacy.get(destination_id)
    if not source_hash or not destination_hash:
        raise FollowValidationError(
            "no page version was recorded with this proposal, so it cannot be checked against the current corpus"
        )
    if source_hash != field.manifest[source_id].sha256:
        raise FollowValidationError(f"source page {source_id!r} has changed since this route was proposed")
    if destination_hash != field.manifest[destination_id].sha256:
        raise FollowValidationError(f"destination page {destination_id!r} has changed since this route was proposed")


def accept(proposal_id: str, *, data_dir: Path = DEFAULT_DATA_DIR) -> str:
    with _STATE_LOCK:
        p = _paths(data_dir)
        proposals = _load(p["proposals"], {})
        rec = next((v for v in proposals.values() if v["proposal_id"] == proposal_id), None)
        if rec is None:
            raise StateError(f"unknown proposal: {proposal_id}")

        bonds = _load(p["bonds"], {})
        existing = next((v for v in bonds.values() if v["proposal_id"] == proposal_id), None)
        if existing:
            return existing["bond_id"]  # repeat-safe

        bond_id = f"bond_{proposal_id}"
        bonds[bond_id] = {
            "bond_id": bond_id,
            "proposal_id": proposal_id,
            "kind": rec.get("kind"),
            "source_id": rec["source_id"],
            "active_id": rec["active_id"],
            "target_id": rec["selected_id"],
            "target_text": rec["selected_text"],
            "field": rec.get("field"),
            "policy": rec.get("policy"),
            "operator": rec.get("operator"),
            "relation_labels": rec.get("relation_labels"),
            "run_dir": rec.get("run_dir"),
            "offer_set_id": rec.get("offer_set_id"),
            **{k: rec[k] for k in _OPTION_FIELDS if k in rec},
            "source_sha256": rec.get("source_sha256"),
            "destination_sha256": rec.get("destination_sha256"),
            "created_at": _now(),
        }
        _save(p["bonds"], bonds)

        rec["status"] = "accepted"
        _save(p["proposals"], proposals)
        return bond_id


def find_follow(follow_token: str | None, *, data_dir: Path = DEFAULT_DATA_DIR) -> dict | None:
    """The recorded traversal made with this `follow_token`, if any."""
    if not follow_token:
        return None
    history = reader_state(data_dir=data_dir).get("history") or []
    return next((h for h in history if h.get("follow_token") == follow_token), None)


def follow(bond_id: str, *, data_dir: Path = DEFAULT_DATA_DIR, follow_token: str | None = None) -> dict:
    """Q: traverse to an accepted bond's target. Does not touch the Gibsey Vault.
    With a `follow_token`, repeating the call is a no-op returning the same state."""
    with _STATE_LOCK:
        p = _paths(data_dir)
        bonds = _load(p["bonds"], {})
        bond = bonds.get(bond_id)
        if bond is None:
            raise StateError(f"unknown bond: {bond_id}")

        state = _load(p["reader_state"], {"active_page": None, "active_passage": None, "history": []})
        if follow_token and any(h.get("follow_token") == follow_token for h in state.get("history", [])):
            return state  # duplicate click: one traversal, one history entry

        entry = {
            "event": "Q_follow",
            "bond_id": bond_id,
            # The bond's own source -- NOT state["active_page"], which only ever reflects the
            # last followed bond and is stale after any manual navigation.
            "from_page": _page_of(bond["source_id"]),
            "from_passage": bond.get("active_id") or bond["source_id"],
            "to_id": bond["target_id"],
            "at": _now(),
        }
        if follow_token:
            entry["follow_token"] = follow_token
        state.setdefault("history", []).append(entry)
        state["active_page"] = bond["target_id"].split(".")[0]
        state["active_passage"] = bond["target_id"]
        _save(p["reader_state"], state)
        return state


def preserve(bond_id: str, *, data_dir: Path = DEFAULT_DATA_DIR) -> str:
    """R: preserve the selected realization's exact text and provenance into the Gibsey
    Vault, independent of the mutable source file path. Repeat-safe per bond_id."""
    with _STATE_LOCK:
        p = _paths(data_dir)
        bonds = _load(p["bonds"], {})
        bond = bonds.get(bond_id)
        if bond is None:
            raise StateError(f"unknown bond: {bond_id}")

        index = _load(p["vault_index"], {})
        existing = next((v for v in index.values() if v["bond_id"] == bond_id), None)
        if existing:
            return existing["entry_id"]  # repeat-safe: no duplicate vault entry

        entry_id = f"vault_{bond_id}"
        entry = {
            "entry_id": entry_id,
            "bond_id": bond_id,
            "source_id": bond["source_id"],
            "active_id": bond["active_id"],
            "target_id": bond["target_id"],
            "target_text": bond["target_text"],
            "preserved_at": _now(),
        }
        p["vault_dir"].mkdir(parents=True, exist_ok=True)
        _save(p["vault_dir"] / f"{entry_id}.json", entry)

        index[entry_id] = {"entry_id": entry_id, "bond_id": bond_id, "target_id": bond["target_id"]}
        _save(p["vault_index"], index)
        return entry_id


def reader_state(*, data_dir: Path = DEFAULT_DATA_DIR) -> dict:
    return _load(_paths(data_dir)["reader_state"], {"active_page": None, "active_passage": None, "history": []})
