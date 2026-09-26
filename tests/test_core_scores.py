"""Executable scores against isolated fixture journals; no model or corpus writes."""
from __future__ import annotations

import copy
import json

import pytest

from gibsey_lab.core import identity, journal, reducer, resolver, scores
from gibsey_lab.core.core import Core, CoreError
from gibsey_lab.core.fixtures import ENTRY_PAGE, demo_field, fixture_options, recurrence_score
from gibsey_lab.core.replay import decision_replay, export_bundle, state_replay


@pytest.fixture
def demo_core(tmp_path):
    return Core(core_dir=tmp_path / "core", field=demo_field(), options_provider=fixture_options)


def start_demo(core, session="recurrence"):
    core.start_session(ENTRY_PAGE, session_id=session, score_config=recurrence_score())
    return session


def select(core, session, destination, *, operator="ECHO", request="selection"):
    offer = core.resolve_options(session, operator)
    bond = next(bond for bond in offer["bonds"] if bond["destination_page"] == destination)
    payload = {
        "offer_set_id": offer["offer_set_id"], "bond_version_id": bond["bond_version_id"],
        "expected_revision": core.state(session).r, "request_id": request,
    }
    return core.execute_action(session, **payload), payload


@pytest.mark.parametrize("path,value", [
    (("schema_version",), True),
    (("score_version",), 0),
    (("score_version",), True),
    (("score_id",), ""),
    (("score_id",), []),
    (("entry_version",), "RX1"),
    (("entry_version",), []),
    (("global_actions",), ["pause", "invent_a_bond"]),
    (("global_actions",), ["pause", "pause"]),
    (("initial_movement",), "missing"),
    (("terminal_movements",), ["outward"]),
    (("terminal_movements",), ["complete", "complete"]),
    (("empty_offer_behavior",), "relax_constraints"),
    (("evidence",), "pretend_supported"),
    (("relocation", "permitted"), "yes"),
    (("relocation", "advances"), True),
    (("movements", "outward", "allowed_operators"), ["RETURN"]),
    (("movements", "outward", "allowed_functions"), ["L"]),
    (("movements", "outward", "allowed_operators"), []),
    (("movements", "outward", "guards"), "target_unvisited"),
    (("movements", "outward", "guards"), ["unknown_predicate"]),
    (("movements", "outward", "guards"), [{"min_intervening_encounters": True}]),
    (("movements", "outward", "guards"), [{"min_intervening_encounters": -1}]),
    (("movements", "outward", "guards"), [{"min_intervening_encounters": 2, "or": "skip"}]),
    (("movements", "outward", "advance_after"), 0),
    (("movements", "outward", "advance_after"), True),
    (("movements", "outward", "next"), "missing"),
    (("movements", "outward", "advance_on"), ["relocation"]),
])
def test_validation_rejects_unknown_or_malformed_definitions(path, value):
    config = recurrence_score()
    target = config
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(scores.ScoreError):
        scores.validate(config)


def test_validation_returns_an_independent_snapshot_and_rejects_extra_keys():
    original = recurrence_score()
    validated = scores.validate(original)
    assert validated == original and validated is not original
    validated["movements"]["outward"]["guards"].append("target_is_entry_version")
    assert original["movements"]["outward"]["guards"] == ["target_unvisited"]
    with pytest.raises(scores.ScoreError):
        scores.validate({**original, "unknown_rule": True})


def test_score_requires_its_exact_entry_version(demo_core):
    with pytest.raises((scores.ScoreError, CoreError)):
        demo_core.start_session("RX3", session_id="wrong_entry", score_config=recurrence_score())
    assert journal.read_events("wrong_entry", demo_core.core_dir) == []


def test_synthetic_fixture_is_separate_and_every_outward_branch_can_return(demo_core):
    field = demo_core.field
    assert field.id == "recurrence-demo"
    assert set(field.manifest) == {"RX1", "RX3", "RX5", "RX7"}
    for page in field.manifest.values():
        assert "Synthetic demonstration" in page.text
        assert not page.path.exists()
    completed = 0
    for first in ("RX3", "RX5", "RX7"):
        for second in ("RX3", "RX5", "RX7"):
            if first == second:
                continue
            session = start_demo(demo_core, f"branch_{first}_{second}")
            select(demo_core, session, first, request="first")
            assert demo_core.state(session).z["counter"] == 1
            select(demo_core, session, second, operator="DEVELOP", request="second")
            state = demo_core.state(session)
            assert state.z["movement"] == "return" and state.z["counter"] == 0
            offer = demo_core.resolve_options(session, "ECHO")
            assert [bond["destination_page"] for bond in offer["bonds"]] == [ENTRY_PAGE]
            select(demo_core, session, ENTRY_PAGE, request="return")
            final = demo_core.state(session)
            assert final.z["status"] == "complete" and final.z["movement"] == "complete"
            assert final.z["counters"] == {"outward": 2, "return": 1}
            assert [encounter["page_id"] for encounter in final.H] == [ENTRY_PAGE, first, second, ENTRY_PAGE]
            assert final.H[-1]["return_index_distance"] == 3
            assert final.H[-1]["intervening_encounters"] == 2
            completed += 1
    assert completed == 6


def test_neutral_can_return_early_and_relocate_without_movement_progress(demo_core):
    demo_core.start_session(ENTRY_PAGE, session_id="neutral_demo")
    select(demo_core, "neutral_demo", "RX3", request="outward")
    select(demo_core, "neutral_demo", ENTRY_PAGE, request="early_return")
    before = demo_core.state("neutral_demo")
    result = demo_core.relocate("neutral_demo", page_id="RX5", expected_revision=before.r,
                                request_id="manual", cause="page_list")
    after = demo_core.state("neutral_demo")
    assert result["status"] == "committed" and after.page == "RX5"
    assert len(after.H) == 4 and after.H[-1]["bond_version_id"] is None
    assert after.z["counter"] == before.z["counter"]
    assert after.z["score_id"] == "neutral" and after.z["status"] == "active"


def test_recurrence_rejects_early_return_and_every_relocation_cause(demo_core):
    session = start_demo(demo_core)
    select(demo_core, session, "RX3", request="outward")
    offer = demo_core.resolve_options(session, "ECHO")
    assert ENTRY_PAGE not in [bond["destination_page"] for bond in offer["bonds"]]
    exclusions = [decision for decision in offer["decisions"]
                  if decision["code"] == "target_already_visited" and decision["destination_page"] == ENTRY_PAGE]
    assert len(exclusions) == 1
    assert exclusions[0]["rule_id"] == "recurrence_fixture@1/outward/target_unvisited"
    assert exclusions[0]["encounter_refs"][0]["encounter_index"] == 0
    before = demo_core.state(session)
    for cause in ("previous", "next", "page_list", "back", "history_back", "history_forward", "resume_here", "other"):
        with pytest.raises(CoreError) as caught:
            demo_core.relocate(session, page_id=ENTRY_PAGE, expected_revision=before.r,
                               request_id=f"blocked_{cause}", cause=cause)
        assert caught.value.code in ("relocation_forbidden", "score_rejected")
        after = demo_core.state(session)
        assert after.H == before.H and after.z == before.z and after.r == before.r


def test_retry_conflict_stale_and_pause_resume_never_advance(demo_core):
    session = start_demo(demo_core)
    unused = demo_core.resolve_options(session, "DEVELOP")
    _, payload = select(demo_core, session, "RX3", request="first")
    before = demo_core.state(session)
    assert demo_core.execute_action(session, **payload)["duplicate"] is True
    with pytest.raises(CoreError) as conflict:
        demo_core.execute_action(session, **{**payload, "bond_version_id": "different"})
    assert conflict.value.code == "request_id_reused"
    with pytest.raises(CoreError) as stale:
        demo_core.execute_action(session, offer_set_id=unused["offer_set_id"],
                                 bond_version_id=unused["bonds"][0]["bond_version_id"],
                                 expected_revision=1, request_id="stale")
    assert stale.value.code == "stale_revision"
    after = demo_core.state(session)
    assert after.z == before.z and after.H == before.H and after.r == before.r
    fresh = demo_core.resolve_options(session, "ECHO")
    demo_core.pause(session)
    paused = demo_core.state(session)
    assert paused.paused and paused.z["counters"] == before.z["counters"]
    demo_core.unpause(session)
    resumed = demo_core.state(session)
    assert not resumed.paused and resumed.z["counters"] == before.z["counters"]
    assert resumed.H == before.H and resumed.offer_sets == {}
    with pytest.raises(CoreError) as invalidated:
        demo_core.execute_action(session, offer_set_id=fresh["offer_set_id"],
                                 bond_version_id=fresh["bonds"][0]["bond_version_id"],
                                 expected_revision=resumed.r, request_id="old_offer_after_resume")
    assert invalidated.value.code == "unknown_or_stale_offer_set"


def test_ordered_histories_with_equal_counts_change_return_eligibility(demo_core):
    config = scores.neutral_score()
    config["score_id"] = "spacing_history_fixture"
    config["movements"]["open"]["guards"] = [{"min_intervening_encounters": 2}]
    offers = []
    for session, route in (("older", ["RX7", "RX3", "RX5"]), ("newer", ["RX3", "RX7", "RX5"])):
        demo_core.start_session(ENTRY_PAGE, session_id=session, score_config=config)
        for index, destination in enumerate(route):
            demo_core.relocate(session, page_id=destination, expected_revision=demo_core.state(session).r,
                               request_id=f"manual_{index}", cause="page_list")
        offers.append(demo_core.resolve_options(session, "ECHO"))
    older, newer = (demo_core.state(session) for session in ("older", "newer"))
    assert older.v == newer.v and older.c == newer.c and older.z["counters"] == newer.z["counters"]
    assert older.H != newer.H
    assert offers[0]["candidate_inputs"] == offers[1]["candidate_inputs"]
    assert offers[0]["resolver_inputs"] == offers[1]["resolver_inputs"]
    assert "RX7" in [bond["destination_page"] for bond in offers[0]["bonds"]]
    assert "RX7" not in [bond["destination_page"] for bond in offers[1]["bonds"]]
    checks = [next(decision for decision in offer["decisions"]
                   if decision["destination_page"] == "RX7" and decision["rule_id"].endswith("/min_intervening_encounters"))
              for offer in offers]
    assert [check["allowed"] for check in checks] == [True, False]
    assert [check["values"]["candidate_arrival_index"] for check in checks] == [4, 4]
    assert [check["values"]["return_index_distance"] for check in checks] == [3, 2]
    assert [check["values"]["intervening_encounters"] for check in checks] == [2, 1]
    assert [check["encounter_refs"][-1]["encounter_index"] for check in checks] == [1, 2]
    assert [check["code"] for check in checks] == ["return_spacing_satisfied", "return_too_soon"]


def test_empty_offer_blocks_without_relaxing_constraints_or_adding_arrivals(demo_core):
    session = start_demo(demo_core)
    before = demo_core.state(session)
    offer = demo_core.resolve_options(session, "BRIDGE")
    blocked = demo_core.state(session)
    assert offer["bonds"] == [] and offer["blocked"]["code"] == "blocked_with_explanation"
    assert blocked.z["status"] == "blocked" and blocked.z["blocked"]
    assert blocked.H == before.H and blocked.z["counters"] == before.z["counters"]
    assert blocked.z["config"] == recurrence_score()
    recovered = demo_core.resolve_options(session, "ECHO")
    assert recovered["bonds"]
    assert demo_core.state(session).z["status"] == "active"
    assert demo_core.state(session).z["counters"] == before.z["counters"]


def test_restart_pins_content_score_and_per_event_progress_with_offline_replay(demo_core, tmp_path):
    session = start_demo(demo_core)
    select(demo_core, session, "RX3", request="first")
    demo_core.pause(session)
    before = demo_core.resume_session(session)
    restarted = Core(core_dir=demo_core.core_dir, field=demo_field(), options_provider=fixture_options)
    assert restarted.resume_session(session) == before
    restarted.unpause(session)
    select(restarted, session, "RX5", request="second")
    select(restarted, session, ENTRY_PAGE, request="return")
    assert state_replay(session, restarted)["ok"]
    assert decision_replay(session, restarted)["ok"]
    trace = reducer.reduce_with_trace(journal.read_events(session, restarted.core_dir))
    actions = [entry["state"]["z"]["counters"] for entry in trace if entry["event"] == "action_committed"]
    assert actions == [{"outward": 1, "return": 0}, {"outward": 2, "return": 0}, {"outward": 2, "return": 1}]
    bundle = json.loads(export_bundle(session, restarted, tmp_path / "bundle").read_text())
    assert bundle["final_state"]["z"]["config"] == recurrence_score()
    assert bundle["final_state"]["z"]["score_version"] == 1
    assert bundle["replay"]["provider_calls"] == 0 and bundle["replay"]["ok"]
    assert all(version["retained"] for version in bundle["versions"].values())


def test_guard_uses_exact_versions_and_latest_prior_encounter():
    field = demo_field()
    entry = identity.version_id(ENTRY_PAGE, field.manifest[ENTRY_PAGE].sha256)
    source = identity.version_id("RX5", field.manifest["RX5"].sha256)
    state = reducer.State(v=source, page="RX5", z=scores.initial(recurrence_score(), entry))
    state.z["movement"] = "return"
    state.H = [{"encounter_index": index, "event_seq": index, "version_id": version}
               for index, version in enumerate([entry, source, entry, source])]
    bond = {"bond_version_id": "spacing_check", "destination_version": entry,
            "destination_page": ENTRY_PAGE, "operator": "ECHO"}
    check = next(decision for decision in scores.evaluate(state, bond)
                 if decision["rule_id"].endswith("/min_intervening_encounters"))
    assert check["values"]["previous_encounter_index"] == 2
    assert check["values"]["intervening_encounters"] == 1 and not check["allowed"]
    assert [reference["encounter_index"] for reference in check["encounter_refs"]] == [0, 2]
    changed = {**bond, "destination_version": "RX1@" + "f" * 12}
    checks = scores.evaluate(state, changed)
    entry_check = next(decision for decision in checks if decision["code"] == "target_not_entry_version")
    assert not entry_check["allowed"]
    assert [reference["encounter_index"] for reference in entry_check["encounter_refs"]] == [0, 2]
    assert any(decision["code"] == "target_not_previously_encountered" for decision in checks)


@pytest.mark.parametrize("advances", [False, True])
def test_permitted_relocation_records_every_arrival_and_only_declared_progress(demo_core, advances):
    config = scores.neutral_score()
    config["score_id"] = "relocation_progress_fixture"
    config["relocation"]["advances"] = advances
    if advances:
        config["movements"]["open"]["advance_on"].append("relocation")
    demo_core.start_session(ENTRY_PAGE, session_id="relocations", score_config=config)
    select(demo_core, "relocations", "RX3", request="first_q")
    before = demo_core.state("relocations")
    payload = {"page_id": "RX5", "expected_revision": before.r, "request_id": "manual", "cause": "page_list"}
    demo_core.relocate("relocations", **payload)
    after = demo_core.state("relocations")
    assert len(after.H) == len(before.H) + 1
    assert after.H[-1]["page_id"] == "RX5" and after.H[-1]["bond_version_id"] is None
    assert after.z["counter"] == before.z["counter"] + int(advances)
    assert after.z["counters"]["open"] == 1 + int(advances)
    assert demo_core.relocate("relocations", **payload)["duplicate"]
    assert demo_core.state("relocations").canonical() == after.canonical()
    assert state_replay("relocations", demo_core)["ok"]
    assert decision_replay("relocations", demo_core)["ok"]


def test_only_declared_successful_action_can_complete_a_movement(demo_core):
    config = scores.neutral_score()
    config["score_id"] = "relocation_only_fixture"
    config["relocation"]["advances"] = True
    config["movements"]["open"].update(advance_on=["relocation"], advance_after=1, next="complete")
    config["terminal_movements"] = ["complete"]
    demo_core.start_session(ENTRY_PAGE, session_id="relocation_only", score_config=config)
    select(demo_core, "relocation_only", "RX3", request="noncounted_q")
    before = demo_core.state("relocation_only")
    assert before.z["counter"] == 0 and before.z["status"] == "active" and len(before.H) == 2
    demo_core.relocate("relocation_only", page_id="RX5", expected_revision=before.r,
                       request_id="counted_manual", cause="page_list")
    after = demo_core.state("relocation_only")
    assert after.z["status"] == "complete" and after.z["counters"] == {"open": 1}
    assert len(after.H) == 3
    assert state_replay("relocation_only", demo_core)["ok"]


@pytest.mark.parametrize("action,outcome", [("exit", "exited"), ("end_journey", "ended_by_reader")])
def test_lifecycle_endings_are_distinct_idempotent_and_preserve_progress(demo_core, action, outcome):
    session = start_demo(demo_core)
    select(demo_core, session, "RX3", request="first")
    demo_core.pause(session)
    before = demo_core.state(session)
    payload = {"action": action, "expected_revision": before.r, "request_id": "ending"}
    result = demo_core.lifecycle(session, **payload)
    after = demo_core.state(session)
    assert result["duplicate"] is False and after.z["status"] == outcome
    assert after.z["counters"] == before.z["counters"] and after.H == before.H
    assert after.r == before.r + 1 and not after.paused and not after.offer_sets
    assert demo_core.lifecycle(session, **payload)["duplicate"]
    assert demo_core.state(session).canonical() == after.canonical()
    with pytest.raises(CoreError) as conflict:
        demo_core.lifecycle(session, **{**payload, "action": "exit" if action == "end_journey" else "end_journey"})
    assert conflict.value.code == "request_id_reused"
    with pytest.raises(CoreError) as finished:
        demo_core.check_relocation(session)
    assert finished.value.code == outcome
    with pytest.raises(CoreError) as paused:
        demo_core.pause(session)
    assert paused.value.code == "performance_finished"
    assert state_replay(session, demo_core)["ok"] and decision_replay(session, demo_core)["ok"]


def test_lifecycle_rejects_stale_and_undeclared_actions_without_progress(demo_core):
    config = recurrence_score()
    config["global_actions"] = ["resume", "exit"]
    demo_core.start_session(ENTRY_PAGE, session_id="limited_actions", score_config=config)
    before = demo_core.state("limited_actions")
    with pytest.raises(CoreError) as forbidden_pause:
        demo_core.pause("limited_actions")
    assert forbidden_pause.value.code == "action_forbidden"
    for action, revision, expected in (("end_journey", before.r, "action_forbidden"), ("exit", 0, "stale_revision")):
        payload = {"action": action, "expected_revision": revision, "request_id": action}
        for duplicate in (False, True):
            with pytest.raises(CoreError) as rejected:
                demo_core.lifecycle("limited_actions", **payload)
            assert rejected.value.code == expected
            if duplicate:
                assert rejected.value.details["duplicate"]
        after = demo_core.state("limited_actions")
        assert after.z == before.z and after.H == before.H and after.r == before.r


def test_explicit_exit_after_success_keeps_successful_completion(demo_core):
    session = start_demo(demo_core)
    for index, destination in enumerate(("RX3", "RX5", ENTRY_PAGE)):
        select(demo_core, session, destination, request=f"step_{index}")
    before = demo_core.state(session)
    demo_core.lifecycle(session, action="exit", expected_revision=before.r, request_id="leave_completed")
    after = demo_core.state(session)
    assert after.z["status"] == "complete"
    assert after.z["counters"] == before.z["counters"] and after.H == before.H
    event = journal.read_events(session, demo_core.core_dir)[-1]
    assert event["event"] == "performance_ended" and event["action"] == "exit"
    assert event["prior_outcome"] == "complete"


def test_hard_guards_and_evidence_precede_display_limits(demo_core):
    session = start_demo(demo_core)
    select(demo_core, session, "RX3", request="first")
    frozen = demo_core.resolve_options(session, "ECHO")
    state = demo_core.state(session)
    candidates = copy.deepcopy(frozen["candidate_inputs"])
    candidates[0]["rank"] = -100
    assert candidates[0]["destination_page"] == ENTRY_PAGE
    candidates[1].update(evidence_allowed=False, evidence_code="version_mismatch", rank=-50)
    inputs = {**frozen["resolver_inputs"], "max_supported": 1, "min_shown": 1}
    result = resolver.resolve(state, candidates, inputs)
    assert [bond["destination_page"] for bond in result["bonds"]] == ["RX7"]
    assert any(check["code"] == "target_already_visited" and not check["allowed"] for check in result["decisions"])
    assert any(check["code"] == "version_mismatch" and not check["allowed"] for check in result["decisions"])
    candidates[2]["policy_allowed"] = False
    blocked = resolver.resolve(state, candidates, inputs)
    assert not blocked["bonds"] and "policy_ineligible" in blocked["blocked"]["reason_codes"]


def test_synthetic_relationships_are_explicitly_labeled_in_retained_inputs(demo_core):
    session = start_demo(demo_core)
    offer = demo_core.resolve_options(session, "ECHO")
    assert all(bond["evidence_kind"] == "synthetic_declared_relationship" for bond in offer["bonds"])
    assert all(bond["wording_source"] == "destination_opening_sentence" for bond in offer["bonds"])


def test_strong_ranking_cannot_override_supported_evidence_floor(demo_core):
    session = start_demo(demo_core)
    offer = demo_core.resolve_options(session, "ECHO")
    candidates = copy.deepcopy(offer["candidate_inputs"])
    candidates[0].update(tier="exploratory", rank=-100)
    candidates[0]["operator_fit"]["score"] = 3.0
    result = resolver.resolve(demo_core.state(session), candidates, {**offer["resolver_inputs"], "max_supported": 1})
    assert result["bonds"][0]["destination_page"] == "RX5"
    assert any(check["destination_page"] == "RX3" and check["code"] == "below_support_floor"
               and not check["allowed"] for check in result["decisions"])


def test_reused_offer_updates_blocked_status_without_arrival_or_progress(demo_core):
    session = start_demo(demo_core)
    available = demo_core.resolve_options(session, "ECHO")
    blocked = demo_core.resolve_options(session, "BRIDGE")
    before = demo_core.state(session)
    assert before.z["status"] == "blocked"
    recovered = demo_core.resolve_options(session, "ECHO")
    active_state = demo_core.state(session)
    assert recovered["offer_set_id"] == available["offer_set_id"]
    assert recovered["bonds"] == available["bonds"] and recovered["decisions"] == available["decisions"]
    assert active_state.z["status"] == "active"
    assert demo_core.resolve_options(session, "ECHO")["reused"]
    assert demo_core.state(session).canonical() == active_state.canonical()
    repeated_block = demo_core.resolve_options(session, "BRIDGE")
    blocked_state = demo_core.state(session)
    assert repeated_block["offer_set_id"] == blocked["offer_set_id"]
    assert blocked_state.z["status"] == "blocked"
    assert blocked_state.H == before.H and blocked_state.z["counters"] == before.z["counters"]
    assert blocked_state.r == before.r
    assert demo_core.resolve_options(session, "BRIDGE")["reused"]
    assert demo_core.state(session).canonical() == blocked_state.canonical()
    assert state_replay(session, demo_core)["ok"] and decision_replay(session, demo_core)["ok"]
