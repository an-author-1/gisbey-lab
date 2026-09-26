"""Scored and historical replay without providers, live stores, or browser effects."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from gibsey_lab.core import identity, journal, reducer, replay, scores
from gibsey_lab.core.core import Core
from tests.test_core_transactions import fake_options, synthetic_field


def recurrence_core(tmp_path):
    core = Core(core_dir=tmp_path / "core", field=synthetic_field(tmp_path / "vault"),
                options_provider=fake_options)
    config = scores.neutral_score()
    config.update(score_id="replay_recurrence_fixture", entry_version=core._version("P1"),
                  initial_movement="outward", relocation={"permitted": False, "advances": False},
                  terminal_movements=["complete"], movements={
                      "outward": {"allowed_functions": ["Q"], "allowed_operators": ["ECHO", "DEVELOP"],
                                  "guards": ["target_unvisited"], "advance_after": 2,
                                  "advance_on": ["Q"], "next": "return"},
                      "return": {"allowed_functions": ["Q"], "allowed_operators": list(identity.OPERATORS),
                                 "guards": ["target_is_entry_version", {"min_intervening_encounters": 2}],
                                 "advance_after": 1, "advance_on": ["Q"], "next": "complete"},
                  })
    core.start_session("P1", session_id="score_replay", score_config=config)
    return core


def follow(core, destination, request_id):
    offered = core.resolve_options("score_replay", "ECHO", policy="include-adjacent")
    selected = next(bond for bond in offered["bonds"] if bond["destination_page"] == destination)
    return core.execute_action("score_replay", offer_set_id=offered["offer_set_id"],
                               bond_version_id=selected["bond_version_id"],
                               expected_revision=core.state("score_replay").r, request_id=request_id)


def unavailable_provider(*args, **kwargs):
    raise AssertionError("replay must not request live candidates or providers")


def test_score_replay_retains_completion_spacing_and_restart_without_provider(tmp_path):
    core = recurrence_core(tmp_path)
    follow(core, "P2", "out-one")
    follow(core, "P3", "out-two")
    follow(core, "P1", "return-home")
    before = core.state("score_replay")
    assert before.z["status"] == "complete"
    assert before.z["counters"] == {"outward": 2, "return": 1}
    assert before.H[-1]["return_index_distance"] == 3
    assert before.H[-1]["intervening_encounters"] == 2
    restarted = Core(core_dir=core.core_dir, field=core.field, options_provider=unavailable_provider)
    assert restarted.state("score_replay").canonical() == before.canonical()
    result = replay.replay("score_replay", restarted)
    assert result["ok"] and result["provider_calls"] == 0
    assert result["decision_replay"]["offer_sets"] == 3
    assert all(item["reasons_equal"] for item in result["decision_replay"]["results"])
    bundle_path = replay.export_bundle("score_replay", restarted, tmp_path / "export")
    bundle = json.loads(bundle_path.read_text())
    assert bundle["schema"] == "journey-bundle/2"
    assert len(bundle["versions"]) == len(core.field.manifest)
    assert bundle["score_snapshots"][before.z["config_sha256"]] == before.z["config"]
    assert len(bundle["state_trace"]) == len(bundle["events"])
    offline = replay.replay_bundle(bundle_path)
    assert offline["ok"] and offline["provider_calls"] == 0


@pytest.mark.parametrize("damage", ["missing_score", "changed_score", "changed_progress", "missing_candidates",
                                    "changed_reason", "changed_content", "missing_content", "missing_bundle_score",
                                    "changed_trace", "changed_manifest"])
def test_offline_replay_reports_missing_or_changed_dependencies(tmp_path, damage):
    core = recurrence_core(tmp_path)
    follow(core, "P2", "out-one")
    bundle = json.loads(replay.export_bundle("score_replay", core, tmp_path / "export").read_text())
    start = bundle["events"][0]
    offer = next(event for event in bundle["events"] if event["event"] == "offer_set_created")
    action = next(event for event in bundle["events"] if event["event"] == "action_committed")
    if damage == "missing_score":
        del start["score_snapshot"]
    elif damage == "changed_score":
        start["score_snapshot"]["score_version"] += 1
    elif damage == "changed_progress":
        action["score_after"]["counter"] += 1
    elif damage == "missing_candidates":
        del offer["candidate_inputs"]
    elif damage == "changed_reason":
        offer["decisions"][0]["code"] = "fabricated_reason"
    elif damage == "changed_content":
        bundle["versions"][start["version_id"]]["text"] += " Changed."
    elif damage == "missing_content":
        del bundle["versions"][start["version_id"]]
    elif damage == "missing_bundle_score":
        del bundle["score_snapshots"]
    elif damage == "changed_trace":
        bundle["state_trace"][0]["state"]["z"]["counter"] += 1
    else:
        bundle["version_manifest"]["score_config_sha256"] = []
    assert replay.replay_bundle(bundle)["ok"] is False


def test_decision_replay_reconstructs_reasons_after_a_consistent_refingerprint(tmp_path):
    core = recurrence_core(tmp_path)
    core.resolve_options("score_replay", "ECHO", policy="include-adjacent")
    events = copy.deepcopy(journal.read_events("score_replay", core.core_dir))
    offer = events[-1]
    offer["decisions"][0]["code"] = "fabricated_reason"
    offer["decision_fingerprint"] = identity._digest({name: offer[name] for name in (
        "candidate_inputs", "resolver_inputs", "score_config_sha256", "bonds", "decisions", "blocked")})
    offer["offer_set_id"] = "offers_" + identity._digest({
        "session_id": "score_replay", "revision": offer["revision"], "source_version": offer["source_version"],
        "operator": offer["operator"], "policy": offer["policy"],
        "score_config_sha256": offer["score_config_sha256"], "decision_fingerprint": offer["decision_fingerprint"],
    })[:20]
    report = replay._decision_report(events, "score_replay")
    assert report["ok"] is False
    assert "decisions" in report["drift"][0]["differences"]
    assert report["drift"][0]["reasons_equal"] is False


def test_legacy_saved_bundle_keeps_state_but_reports_absent_offline_decision_inputs():
    path = Path(__file__).resolve().parents[1] / "data/verification/core_v03_session2_demo_2026-09-25/journey_s_10169fa2df45.json"
    bundle = json.loads(path.read_text())
    report = replay.replay_bundle(bundle)
    assert report["state_replay"]["ok"]
    assert report["decision_replay"]["offer_sets"] == 2
    assert report["decision_replay"]["available"] is False
    assert {item["reason"] for item in report["decision_replay"]["drift"]} == {"legacy_bundle_missing_frozen_inputs"}
    assert report["recorded_historical_replay"]["ok"]
    assert report["ok"] is False


def test_legacy_live_decision_replay_uses_supplied_atlas_and_no_relocation_offers(tmp_path):
    path = Path(__file__).resolve().parents[1] / "data/verification/core_v03_session2_demo_2026-09-25/journey_s_10169fa2df45.json"
    bundle = json.loads(path.read_text())
    session_id = bundle["session_id"]
    destination = journal.journal_path(session_id, tmp_path / "legacy")
    destination.parent.mkdir(parents=True)
    destination.write_text("\n".join(json.dumps(event) for event in bundle["events"]) + "\n")
    core = Core(core_dir=tmp_path / "legacy")
    report = replay.replay(session_id, core)
    assert report["ok"] and report["provider_calls"] == 0
    assert report["decision_replay"]["offer_sets"] == 2
    assert core.state(session_id).canonical() == bundle["final_state"]
    assert reducer.reduce(bundle["events"]).z == {"score_id": "neutral", "score_version": 1, "movement": "open"}


@pytest.mark.parametrize("directory,filename,offer_count", [
    ("core_v03_demo_2026-09-25", "journey_s_0103376737a9.json", 1),
    ("core_v03_session2_demo_2026-09-25", "journey_s_10169fa2df45.json", 2),
])
def test_legacy_export_replay_explicitly_uses_supplied_local_atlas(directory, filename, offer_count):
    path = Path(__file__).resolve().parents[1] / "data/verification" / directory / filename
    bundle = json.loads(path.read_text())
    original = copy.deepcopy(bundle)
    report = replay.replay_bundle(bundle, legacy_core=Core())
    assert report["ok"] and report["provider_calls"] == 0
    assert report["decision_replay"]["offer_sets"] == offer_count
    assert all(item["compatibility"] == "legacy_supplied_atlas" for item in report["decision_replay"]["results"])
    assert report["retained_content"]["scope"] == "legacy_encountered_versions"
    assert bundle == original
    if offer_count == 1:
        assert report["state_replay"]["compatibility"] == [
            "legacy_action_request_kind_defaults", "legacy_encounter_cause_defaults"]
