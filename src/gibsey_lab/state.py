"""Minimal explicit Q and R actions.

A Jev selection (a run's result.json) is only a candidate bond proposal. Nothing here
runs automatically after `run-case` — propose / accept / follow / preserve are separate,
explicit steps, matching the QDPI distinction between discovery, acceptance, traversal
(Q), and preservation (R).

The reader's Gibsey Vault (data/gibsey_vault/) is distinct from the Obsidian source vault
(vault/): the former holds a reader's explicitly preserved selections, not authored source.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "data"


class StateError(Exception):
    pass


def _load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


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


def propose(run_dir: Path, *, data_dir: Path = DEFAULT_DATA_DIR) -> str:
    run_dir = Path(run_dir)
    input_record = json.loads((run_dir / "input.json").read_text())
    result = json.loads((run_dir / "result.json").read_text())
    run_id = input_record["run_id"]

    p = _paths(data_dir)
    proposals = _load(p["proposals"], {})
    if run_id in proposals:
        return proposals[run_id]["proposal_id"]  # repeat-safe: same run, same proposal

    if result is None:
        raise StateError("cannot propose from a run with no validated outcome (failed/error run)")
    if result.get("is_abstention"):
        raise StateError("cannot propose a bond: this run abstained (NONE) — there is no destination")

    proposal_id = f"prop_{run_id}"
    proposals[run_id] = {
        "proposal_id": proposal_id,
        "run_id": run_id,
        "case_id": input_record["case_id"],
        "source_id": input_record["source_id"],
        "active_id": input_record["active_id"],
        "selected_id": result["selected_id"],
        "selected_text": result["selected_text"],
        "confidence": result["confidence"],
        "status": "proposed",
        "created_at": _now(),
    }
    _save(p["proposals"], proposals)
    return proposal_id


def accept(proposal_id: str, *, data_dir: Path = DEFAULT_DATA_DIR) -> str:
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
        "source_id": rec["source_id"],
        "active_id": rec["active_id"],
        "target_id": rec["selected_id"],
        "target_text": rec["selected_text"],
        "created_at": _now(),
    }
    _save(p["bonds"], bonds)

    rec["status"] = "accepted"
    _save(p["proposals"], proposals)
    return bond_id


def follow(bond_id: str, *, data_dir: Path = DEFAULT_DATA_DIR) -> dict:
    """Q: traverse to an accepted bond's target. Does not touch the Gibsey Vault."""
    p = _paths(data_dir)
    bonds = _load(p["bonds"], {})
    bond = bonds.get(bond_id)
    if bond is None:
        raise StateError(f"unknown bond: {bond_id}")

    state = _load(p["reader_state"], {"active_page": None, "active_passage": None, "history": []})
    state["history"].append(
        {
            "event": "Q_follow",
            "bond_id": bond_id,
            "from_page": state.get("active_page"),
            "from_passage": state.get("active_passage"),
            "to_id": bond["target_id"],
            "at": _now(),
        }
    )
    state["active_page"] = bond["target_id"].split(".")[0]
    state["active_passage"] = bond["target_id"]
    _save(p["reader_state"], state)
    return state


def preserve(bond_id: str, *, data_dir: Path = DEFAULT_DATA_DIR) -> str:
    """R: preserve the selected realization's exact text and provenance into the Gibsey
    Vault, independent of the mutable source file path. Repeat-safe per bond_id."""
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
