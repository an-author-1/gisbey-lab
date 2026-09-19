import json

import pytest

from gibsey_lab import state


def _write_run(run_dir, *, case_id="f12-micro", selected_id="F12.S6", is_abstention=False):
    run_dir.mkdir(parents=True)
    run_id = run_dir.name
    (run_dir / "input.json").write_text(json.dumps({
        "run_id": run_id, "case_id": case_id, "source_id": "F12", "active_id": "F12.S4",
    }))
    (run_dir / "result.json").write_text(json.dumps(
        None if is_abstention is None else {
            "is_abstention": is_abstention,
            "selected_id": None if is_abstention else selected_id,
            "selected_text": None if is_abstention else "the resolved exact text",
            "confidence": 0.8,
        }
    ))
    return run_id


def test_propose_then_accept_then_follow_then_preserve(tmp_path):
    data_dir = tmp_path / "data"
    run_dir = tmp_path / "runs" / "run1"
    _write_run(run_dir)

    proposal_id = state.propose(run_dir, data_dir=data_dir)
    assert proposal_id.startswith("prop_")

    # Requesting a proposal alone must not move the reader.
    assert state.reader_state(data_dir=data_dir)["active_page"] is None

    bond_id = state.accept(proposal_id, data_dir=data_dir)
    assert bond_id.startswith("bond_")
    assert state.reader_state(data_dir=data_dir)["active_page"] is None  # accept alone doesn't move reader either

    new_state = state.follow(bond_id, data_dir=data_dir)
    assert new_state["active_passage"] == "F12.S6"
    assert len(new_state["history"]) == 1

    entry_id = state.preserve(bond_id, data_dir=data_dir)
    index = json.loads((data_dir / "gibsey_vault" / "index.json").read_text())
    assert entry_id in index

    entry = json.loads((data_dir / "gibsey_vault" / f"{entry_id}.json").read_text())
    assert entry["target_text"] == "the resolved exact text"


def test_propose_is_repeat_safe(tmp_path):
    data_dir = tmp_path / "data"
    run_dir = tmp_path / "runs" / "run1"
    _write_run(run_dir)
    a = state.propose(run_dir, data_dir=data_dir)
    b = state.propose(run_dir, data_dir=data_dir)
    assert a == b


def test_accept_is_repeat_safe_no_duplicate_bond(tmp_path):
    data_dir = tmp_path / "data"
    run_dir = tmp_path / "runs" / "run1"
    _write_run(run_dir)
    proposal_id = state.propose(run_dir, data_dir=data_dir)
    b1 = state.accept(proposal_id, data_dir=data_dir)
    b2 = state.accept(proposal_id, data_dir=data_dir)
    assert b1 == b2
    bonds = json.loads((data_dir / "bonds.json").read_text())
    assert len(bonds) == 1


def test_preserve_is_repeat_safe_no_duplicate_vault_entry(tmp_path):
    data_dir = tmp_path / "data"
    run_dir = tmp_path / "runs" / "run1"
    _write_run(run_dir)
    proposal_id = state.propose(run_dir, data_dir=data_dir)
    bond_id = state.accept(proposal_id, data_dir=data_dir)
    e1 = state.preserve(bond_id, data_dir=data_dir)
    e2 = state.preserve(bond_id, data_dir=data_dir)
    assert e1 == e2
    index = json.loads((data_dir / "gibsey_vault" / "index.json").read_text())
    assert len(index) == 1


def test_cannot_propose_from_abstained_run(tmp_path):
    data_dir = tmp_path / "data"
    run_dir = tmp_path / "runs" / "run1"
    _write_run(run_dir, is_abstention=True)
    with pytest.raises(state.StateError, match="abstained"):
        state.propose(run_dir, data_dir=data_dir)


def test_cannot_propose_from_failed_run(tmp_path):
    data_dir = tmp_path / "data"
    run_dir = tmp_path / "runs" / "run1"
    _write_run(run_dir, is_abstention=None)  # result.json is null: failed/error run
    with pytest.raises(state.StateError, match="no validated outcome"):
        state.propose(run_dir, data_dir=data_dir)


def test_accept_unknown_proposal_raises(tmp_path):
    with pytest.raises(state.StateError, match="unknown proposal"):
        state.accept("prop_does_not_exist", data_dir=tmp_path / "data")


def test_follow_unknown_bond_raises(tmp_path):
    with pytest.raises(state.StateError, match="unknown bond"):
        state.follow("bond_does_not_exist", data_dir=tmp_path / "data")
