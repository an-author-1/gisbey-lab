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


# --- follow records the bond's own source; follow-time validation; idempotent follow ---

def _accepted_bond(tmp_path):
    data_dir = tmp_path / "data"
    run_dir = tmp_path / "runs" / "run1"
    _write_run(run_dir)
    return data_dir, state.accept(state.propose(run_dir, data_dir=data_dir), data_dir=data_dir)


def test_follow_records_from_page_as_the_bonds_source_not_the_stale_active_page(tmp_path):
    """The audited bug: after manual navigation the stored active_page is stale, and
    follow used to write it as from_page."""
    data_dir, bond_id = _accepted_bond(tmp_path)
    (data_dir / "reader_state.json").write_text(json.dumps(
        {"active_page": "PR9", "active_passage": "PR9", "history": []}))  # stale: reader has since moved by hand

    entry = state.follow(bond_id, data_dir=data_dir)["history"][-1]
    assert entry["from_page"] == "F12"  # the bond's source page
    assert entry["from_passage"] == "F12.S4"
    assert entry["to_id"] == "F12.S6"


def test_follow_is_idempotent_per_follow_token(tmp_path):
    data_dir, bond_id = _accepted_bond(tmp_path)
    first = state.follow(bond_id, data_dir=data_dir, follow_token="tok")
    second = state.follow(bond_id, data_dir=data_dir, follow_token="tok")
    assert len(first["history"]) == 1 and second == first
    assert state.find_follow("tok", data_dir=data_dir)["bond_id"] == bond_id
    assert len(state.follow(bond_id, data_dir=data_dir, follow_token="other")["history"]) == 2  # a new, explicit follow


def test_new_proposals_and_bonds_record_field_policy_and_both_endpoint_hashes(tmp_path):
    data_dir = tmp_path / "data"
    run_dir = tmp_path / "runs" / "run1"
    run_dir.mkdir(parents=True)
    (run_dir / "input.json").write_text(json.dumps({
        "run_id": "run1", "case_id": "c", "source_id": "PR1", "active_id": None,
        "reader_state": {"field": "full-41", "policy": "discovery", "operator": "DEVELOP", "criteria_version": "v0.2"},
        "corpus_hashes": {"PR1": "a" * 64, "PR4": "b" * 64},
    }))
    (run_dir / "result.json").write_text(json.dumps(
        {"is_abstention": False, "selected_id": "PR4", "selected_text": "t", "confidence": 0.4}))
    bond_id = state.accept(state.propose(run_dir, data_dir=data_dir), data_dir=data_dir)
    bond = state.get_bond(bond_id, data_dir=data_dir)
    assert (bond["source_sha256"], bond["destination_sha256"]) == ("a" * 64, "b" * 64)
    assert bond["field"] == "full-41" and bond["policy"] == "discovery"


class _FakePage:
    def __init__(self, sha256):
        self.sha256 = sha256


class _FakeField:
    id = "tiny"

    def __init__(self, hashes, excluded=()):
        self.manifest = {pid: _FakePage(sha) for pid, sha in hashes.items()}
        self._excluded = set(excluded)

    def eligible_candidate_ids(self, source_id, policy):
        if policy not in ("discovery", "include-adjacent"):
            raise ValueError(f"unknown policy {policy}")
        excluded = self._excluded if policy == "discovery" else set()
        return [pid for pid in self.manifest if pid != source_id and pid not in excluded]


def _record(**overrides):
    record = {"source_id": "A1", "selected_id": "A3", "field": "tiny", "policy": "discovery",
              "source_sha256": "sa", "destination_sha256": "sc"}
    record.update(overrides)
    return record


def test_validate_movement_accepts_a_current_eligible_route():
    field = _FakeField({"A1": "sa", "A2": "sb", "A3": "sc"}, excluded={"A2"})
    state.validate_movement(_record(), field=field, from_page="A1", client_page="A1")


@pytest.mark.parametrize("record,kwargs,match", [
    (_record(selected_id="Z9"), {"from_page": "A1"}, "not a page in field"),
    (_record(selected_id="A2", destination_sha256="sb"), {"from_page": "A1"}, "not eligible"),
    (_record(destination_sha256="old"), {"from_page": "A1"}, "destination page 'A3' has changed"),
    (_record(source_sha256="old"), {"from_page": "A1"}, "source page 'A1' has changed"),
    (_record(), {"from_page": "A2"}, "starts from 'A1'"),
    (_record(), {"from_page": "A1", "client_page": "A3"}, "starts from 'A1'"),
    (_record(), {"from_page": None}, "missing from_page"),
    (_record(field="other"), {"from_page": "A1"}, "was made in field"),
    (_record(source_sha256=None, destination_sha256=None), {"from_page": "A1"}, "no page version was recorded"),
])
def test_validate_movement_rejections(record, kwargs, match):
    field = _FakeField({"A1": "sa", "A2": "sb", "A3": "sc"}, excluded={"A2"})
    with pytest.raises(state.FollowValidationError, match=match):
        state.validate_movement(record, field=field, **kwargs)


def test_legacy_bond_without_hashes_or_policy_is_validated_against_its_runs_recorded_hashes(tmp_path):
    """Historical bonds.json entries carry no hashes/policy and are never rewritten: the
    originating run's corpus_hashes and recorded policy are used instead."""
    runs_dir = tmp_path / "runs"
    (runs_dir / "legacy_run").mkdir(parents=True)
    (runs_dir / "legacy_run" / "input.json").write_text(json.dumps({
        "run_id": "legacy_run", "reader_state": {"policy": "discovery"}, "corpus_hashes": {"A1": "sa", "A3": "sc", "A2": "sb"},
    }))
    legacy_bond = {"bond_id": "bond_prop_legacy_run", "proposal_id": "prop_legacy_run",
                   "source_id": "A1", "active_id": None, "target_id": "A3", "target_text": "t"}
    current = _FakeField({"A1": "sa", "A2": "sb", "A3": "sc"}, excluded={"A2"})
    state.validate_movement(legacy_bond, field=current, from_page="A1", runs_dir=runs_dir)

    changed = _FakeField({"A1": "sa", "A2": "sb", "A3": "rewritten"}, excluded={"A2"})
    with pytest.raises(state.FollowValidationError, match="has changed"):
        state.validate_movement(legacy_bond, field=changed, from_page="A1", runs_dir=runs_dir)

    neighbor_bond = {**legacy_bond, "target_id": "A2"}
    with pytest.raises(state.FollowValidationError, match="not eligible"):  # the run's recorded policy, not a lax default
        state.validate_movement(neighbor_bond, field=current, from_page="A1", runs_dir=runs_dir)


def test_offer_proposals_require_both_hashes_and_are_repeat_safe(tmp_path):
    data_dir = tmp_path / "data"
    kwargs = dict(offer_set_id="offers_1", field="full-41", policy="discovery", source_id="PR2", source_sha256="s",
                  destination_id="PR5", destination_sha256="d", destination_text="text", relation_labels=["DEVELOP"])
    a = state.propose_offer(data_dir=data_dir, **kwargs)
    assert a == state.propose_offer(data_dir=data_dir, **kwargs)
    assert state.reader_state(data_dir=data_dir)["active_page"] is None  # proposing never moves the reader
    with pytest.raises(state.StateError, match="sha256"):
        state.propose_offer(data_dir=data_dir, **{**kwargs, "destination_sha256": None})


def test_historical_state_files_without_the_new_fields_stay_usable(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "proposals.json").write_text(json.dumps({"old_run": {
        "proposal_id": "prop_old_run", "run_id": "old_run", "case_id": "c", "source_id": "PR1", "active_id": None,
        "selected_id": "PR4", "selected_text": "t", "confidence": 0.3, "status": "proposed", "created_at": "2026-09-20T00:00:00+00:00"}}))
    bond_id = state.accept("prop_old_run", data_dir=data_dir)
    assert state.follow(bond_id, data_dir=data_dir)["history"][0]["from_page"] == "PR1"
    assert json.loads((data_dir / "proposals.json").read_text())["old_run"]["created_at"] == "2026-09-20T00:00:00+00:00"
