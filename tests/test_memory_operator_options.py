import argparse
import copy
import json
import random

import pytest

from gibsey_lab.memory import cli, contextual, operator_options as oo, packet as pk, shortlist as sl
from test_memory_helpers import ScriptedDispatch, atlas_config, by_candidate, ev, make_field, make_rows

SOURCE = "PR2"
EXPLORATORY_LABEL = "Exploratory — weak or uncertain fit"


@pytest.fixture(autouse=True)
def stores(tmp_path, monkeypatch):
    monkeypatch.setattr(contextual, "ASSESSMENTS_PATH", tmp_path / "contextual" / "assessments.jsonl")
    return tmp_path


def options(field, operator, scores=None, *, policy="discovery", rows=None, **kw):
    rows = rows if rows is not None else make_rows(field, SOURCE, scores or {}, **{
        k: kw.pop(k) for k in ("statuses", "default_status") if k in kw})
    return oo.operator_options(field, SOURCE, operator, policy=policy, mode="mock",
                               profiles_provider=lambda source, mode: rows, atlas_config_provider=atlas_config, **kw)


def ids(result):
    return [o["destination_id"] for o in result["options"]]


def test_contract_constants_and_shape():
    assert oo.OPERATOR_DIMENSIONS == {"ECHO": "echo", "DEVELOP": "development", "CONTRADICT": "contradiction",
                                      "BRIDGE": "bridge_relation"}
    assert oo.OPTIONS_POLICY_VERSION == "operator-options-v1" and oo.SUPPORT_FLOOR == sl.RELATION_FLOOR == 2 / 3
    field = make_field()
    result = options(field, "develop", {"LF2": {"development": 0.9}})
    assert result["schema"] == "operator-options/1" and result["operator"] == "DEVELOP" and result["dimension"] == "development"
    assert result["ordering_basis"] == "base_assessments" and result["state"] == "options" and result["mode"] == "mock"
    assert result["page_sha256"] == field.manifest[SOURCE].sha256 and result["atlas_config_id"] == "cfg-mock"
    assert set(result["counts"]) >= {"eligible", "usable", "unusable", "supported", "exploratory_shown", "ineligible_policy"}
    option = result["options"][0]
    assert set(option) >= {"destination_id", "destination_sha256", "tier", "tier_label", "operator_fit", "cautions", "base",
                           "assessment_id", "is_authored_neighbor", "rank", "rank_reasons"}
    assert option["operator_fit"] == {"dimension": "development", "score": pytest.approx(2.7), "score_norm": 0.9,
                                      "confidence": 0.8, "nearest_level": 3}
    assert set(option["base"]) == set(sl.ALL_DIMENSIONS) and option["assessment_id"] == "atlas_PR2_LF2"
    with pytest.raises(ValueError):
        options(field, "INTENSIFY")


def test_every_eligible_complete_profile_is_considered_not_an_old_shortlist():
    """The reproduced defect: a strong DEVELOP destination that the global shortlist never
    admitted (its top-2-per-relation slots and direct_q_fit gate) must still rank first."""
    field = make_field()
    scores = {"P4": {"development": 0.95, "direct_q_fit": 0.2},          # old shortlist gate would drop it
              "LF1": {"development": 0.9}, "LF2": {"development": 0.85}, "LF3": {"development": 0.8}}
    old = sl.build_shortlist(make_rows(field, SOURCE, scores), field.eligible_candidate_ids(SOURCE, "discovery"),
                             page_order=field.all_ids())
    assert "P4" not in [e["destination_id"] for e in old["entries"]] and len(old["entries"]) == 2
    result = options(field, "DEVELOP", scores)
    assert ids(result) == ["P4", "LF1", "LF2", "LF3"] and result["counts"]["usable"] == 15
    assert all(o["tier"] == "supported" and o["tier_label"] == "Supported" for o in result["options"])
    assert result["options"][0]["cautions"] == ["low_direct_q_fit"]  # flagged, not excluded


def test_supported_first_then_exploratory_fill_to_three_and_labeled():
    field = make_field()
    result = options(field, "CONTRADICT", {"LF4": {"contradiction": 0.7}, "P2": {"contradiction": 0.62},
                                           "PR6": {"contradiction": 0.4}, "LF1": {"contradiction": 0.3}})
    assert [(o["destination_id"], o["tier"], o["rank"]) for o in result["options"]] == [
        ("LF4", "supported", 1), ("P2", "exploratory", 2), ("PR6", "exploratory", 3)]
    assert [o["tier_label"] for o in result["options"]] == ["Supported", EXPLORATORY_LABEL, EXPLORATORY_LABEL]
    assert result["counts"]["supported"] == 1 and result["counts"]["exploratory_shown"] == 2
    assert "shown to reach 3 options; only 1 supported" in result["options"][1]["rank_reasons"][-1]


def test_scores_never_altered_and_weak_contradiction_never_supported():
    field = make_field()
    scores = {"P2": {"contradiction": 0.62, "redundancy": 0.9}, "LF4": {"contradiction": 2.0 / 3}}
    rows = make_rows(field, SOURCE, scores)
    before = copy.deepcopy(rows)
    result = options(field, "CONTRADICT", rows=rows)
    assert rows == before
    by_id = {o["destination_id"]: o for o in result["options"]}
    assert by_id["LF4"]["tier"] == "supported"  # an expected score of exactly 2.0 of 3 clears the floor
    assert by_id["P2"]["tier"] == "exploratory" and by_id["P2"]["tier_label"] == EXPLORATORY_LABEL
    assert by_id["P2"]["operator_fit"]["score_norm"] == 0.62 and by_id["P2"]["base"]["contradiction"]["score_norm"] == 0.62
    assert by_id["P2"]["operator_fit"]["score"] == pytest.approx(0.62 * 3) and by_id["P2"]["operator_fit"]["nearest_level"] == 2


def test_supported_list_is_capped_and_never_filled_when_enough():
    field = make_field()
    scores = {pid: {"echo": 0.7 + i * 0.01} for i, pid in enumerate(["LF1", "LF2", "LF3", "LF4", "LF5", "LF6", "P1"])}
    result = options(field, "ECHO", scores)
    assert ids(result) == ["P1", "LF6", "LF5", "LF4", "LF3"] and result["counts"]["supported"] == 7
    assert result["counts"]["supported_shown"] == 5 and result["counts"]["exploratory_shown"] == 0
    assert ids(options(field, "ECHO", scores, max_supported=2, min_shown=2)) == ["P1", "LF6"]


def test_all_weak_atlas_still_yields_three_exploratory_options():
    field = make_field()
    result = options(field, "BRIDGE", {})
    assert result["state"] == "options" and ids(result) == ["LF1", "LF2", "LF3"]  # all tied: field page order
    assert all(o["tier"] == "exploratory" and o["operator_fit"]["score_norm"] == 0.0 for o in result["options"])
    assert result["counts"]["supported"] == 0 and result["counts"]["exploratory_shown"] == 3


def test_tie_break_is_direct_q_fit_then_page_order():
    field = make_field()
    result = options(field, "ECHO", {"P3": {"echo": 0.8, "direct_q_fit": 1.0}, "LF2": {"echo": 0.8}, "LF1": {"echo": 0.8}})
    assert ids(result) == ["P3", "LF1", "LF2"]


def test_unusable_profiles_are_listed_and_never_ranked_as_zero():
    field = make_field()
    rows = make_rows(field, SOURCE, {"LF5": {"development": 0.1}, "LF6": {"development": 0.9}},
                     statuses={"LF1": "stale", "LF2": "failed", "LF3": "unassessed"})
    next(r for r in rows if r["destination_id"] == "LF6")["destination_sha256"] = "0" * 64   # assessed another version
    rows = [r for r in rows if r["destination_id"] != "LF4"]                                 # no row at all
    result = options(field, "DEVELOP", rows=rows)
    assert result["unusable"] == [
        {"destination_id": "LF1", "status": "stale"}, {"destination_id": "LF2", "status": "failed"},
        {"destination_id": "LF3", "status": "unassessed"}, {"destination_id": "LF4", "status": "missing"},
        {"destination_id": "LF6", "status": "hash_mismatch"}]
    assert result["counts"]["unusable"] == 5 and result["counts"]["usable"] == 10
    assert not set(ids(result)) & {"LF1", "LF2", "LF3", "LF4", "LF6"}
    assert ids(result)[0] == "LF5"  # a real 0.1 outranks every real 0.0; unusable pages are not "0.0" candidates


def test_fewer_than_three_eligible_and_no_candidates_and_unavailable_atlas():
    small = make_field({"PR": 5})
    rows = make_rows(small, SOURCE, {"PR4": {"echo": 0.9}})
    result = oo.operator_options(small, SOURCE, "ECHO", policy="discovery", mode="mock",
                                 profiles_provider=lambda s, m: rows, atlas_config_provider=atlas_config)
    assert result["state"] == "fewer_than_three_eligible" and ids(result) == ["PR4", "PR5"]
    assert result["counts"]["eligible"] == 2 and result["counts"]["ineligible_policy"] == 2
    tiny = make_field({"PR": 3})
    none = oo.operator_options(tiny, SOURCE, "ECHO", policy="discovery", mode="mock",
                               profiles_provider=lambda s, m: [], atlas_config_provider=atlas_config)
    assert none["state"] == "no_candidates" and none["options"] == []

    def broken(source, mode):
        raise OSError("atlas store unreadable")

    field = make_field()
    down = oo.operator_options(field, SOURCE, "ECHO", policy="discovery", mode="mock", profiles_provider=broken,
                               atlas_config_provider=atlas_config)
    assert down["state"] == "atlas_unavailable" and "atlas store unreadable" in down["errors"][0]
    unbuilt = options(field, "ECHO", default_status="unassessed")
    assert unbuilt["state"] == "atlas_unavailable" and unbuilt["state_detail"] == "no_usable_profiles"
    assert unbuilt["options"] == [] and len(unbuilt["unusable"]) == 15


def test_discovery_excludes_neighbors_and_include_adjacent_admits_them():
    field = make_field()
    scores = {"PR1": {"development": 1.0}, "PR3": {"development": 0.95}, "LF2": {"development": 0.7}}
    discovery = options(field, "DEVELOP", scores)
    assert not set(ids(discovery)) & {"PR1", "PR3"} and discovery["counts"]["ineligible_policy"] == 2
    adjacent = options(field, "DEVELOP", scores, policy="include-adjacent")
    assert ids(adjacent) == ["PR1", "PR3", "LF2"] and adjacent["counts"]["ineligible_policy"] == 0
    assert [o["is_authored_neighbor"] for o in adjacent["options"]] == [True, True, False]
    assert discovery["option_set_id"] != adjacent["option_set_id"]


def test_deterministic_and_stable_content_hash_id():
    field = make_field()
    scores = {"LF2": {"echo": 0.7}, "LF3": {"echo": 0.7}, "P2": {"echo": 0.9, "development": 0.8}}
    rows = make_rows(field, SOURCE, scores)
    first = options(field, "ECHO", rows=rows)
    for seed in range(4):
        shuffled = copy.deepcopy(rows)
        random.Random(seed).shuffle(shuffled)
        assert options(field, "ECHO", rows=shuffled) == first
    assert first["option_set_id"].startswith("opts_") and "at" not in first
    assert options(field, "DEVELOP", rows=rows)["option_set_id"] != first["option_set_id"]
    changed = make_rows(field, SOURCE, {**scores, "LF2": {"echo": 0.71}})
    assert options(field, "ECHO", rows=changed)["option_set_id"] != first["option_set_id"]
    json.dumps(first)  # serializable as-is


def test_cautions_are_flags_only():
    field = make_field()
    scores = {"LF1": {"echo": 0.9, "redundancy": 1.0, "missing_context": 0.7, "direct_q_fit": 0.1},
              "LF2": {"echo": 0.8}, "LF3": {"echo": 0.7}}
    rows = make_rows(field, SOURCE, scores)
    next(r for r in rows if r["destination_id"] == "LF1")["dimensions"]["echo"]["confidence"] = 0.3
    result = options(field, "ECHO", rows=rows)
    assert ids(result) == ["LF1", "LF2", "LF3"]  # the flagged page keeps its place and its tier
    lf1 = result["options"][0]
    assert lf1["cautions"] == ["low_confidence", "high_redundancy", "high_missing_context", "low_direct_q_fit"]
    assert lf1["tier"] == "supported" and lf1["operator_fit"]["score_norm"] == 0.9 and result["options"][1]["cautions"] == []


# --------------------------------------------------------------------------- refinement

REFINE_SCORES = {"LF1": {"development": 0.9}, "LF2": {"development": 0.8}, "LF3": {"development": 0.7},
                 "P1": {"development": 0.5}}
EVENTS = [ev("page_viewed", "PR5", via="dropdown"), ev("page_viewed", "PR2", via="dropdown")]


def refine(field, option_set, dispatch, events=EVENTS, **kw):
    kw.setdefault("mode", "mock")
    return oo.refine_with_history(option_set, field, events, dispatch=dispatch, requested_model="jev-test", **kw)


def test_refinement_sends_the_history_and_assesses_exactly_the_displayed_options():
    field = make_field()
    base = options(field, "DEVELOP", REFINE_SCORES)
    assert ids(base) == ["LF1", "LF2", "LF3"]
    dispatch = ScriptedDispatch()
    snapshot = copy.deepcopy(base)
    refined = refine(field, base, dispatch, intention="the mirror")
    assert base == snapshot  # the input option set is not mutated
    assert len(dispatch.requests) == 3
    sent = {r.state["candidate_destination"]["text"] for r in dispatch.requests}
    assert sent == {field.manifest[p].text for p in ("LF1", "LF2", "LF3")}
    for request in dispatch.requests:
        history = request.state["reading_history"]
        assert [e["text"] for e in history["encounters"]] == [field.manifest["PR5"].text]
        assert history["reader_stated_intention"] == "the mirror"
        assert request.state["current_page"]["text"] == field.manifest["PR2"].text and request.questions == contextual.QUESTIONS
    packet = pk.build_memory_packet(field, SOURCE, EVENTS, candidate_policy="discovery", intention="the mirror")
    assert refined["refinement"]["memory_sha256"] == pk.memory_sha256(packet)
    assert refined["refinement"]["state"] == "ok" and refined["ordering_basis"] == "reading_history"
    assert refined["refinement"]["assessed_ids"] == ["LF1", "LF2", "LF3"] and refined["option_set_id"] == base["option_set_id"]
    assert all(o["contextual"]["layer"] == "history_conditioned" for o in refined["options"])


def test_refinement_reorders_only_within_tier_and_never_changes_tier_or_labels():
    field = make_field()
    base = options(field, "CONTRADICT", {"LF1": {"contradiction": 0.9}, "LF2": {"contradiction": 0.8},
                                         "P1": {"contradiction": 0.5}, "P2": {"contradiction": 0.4}}, min_shown=4)
    assert [(o["destination_id"], o["tier"]) for o in base["options"]] == [
        ("LF1", "supported"), ("LF2", "supported"), ("P1", "exploratory"), ("P2", "exploratory")]
    script = by_candidate(field, {"LF1": (1.0, 2.0, 0.0), "LF2": (2.0, 2.0, 0.0), "P1": (2.0, 2.0, 0.0), "P2": (3.0, 2.0, 0.0)})
    refined = refine(field, base, ScriptedDispatch(script))
    # P2 works best of all but stays below both supported options; within each tier history reorders
    assert [(o["destination_id"], o["tier"], o["rank"], o["base_rank"]) for o in refined["options"]] == [
        ("LF2", "supported", 1, 2), ("LF1", "supported", 2, 1), ("P2", "exploratory", 3, 4), ("P1", "exploratory", 4, 3)]
    before = {o["destination_id"]: o for o in base["options"]}
    for option in refined["options"]:
        original = before[option["destination_id"]]
        for key in ("tier", "tier_label", "operator_fit", "base", "cautions", "rank_reasons"):
            assert option[key] == original[key]


def test_tie_band_keeps_base_order():
    field = make_field()
    base = options(field, "DEVELOP", REFINE_SCORES)
    near = by_candidate(field, {"LF1": (2.0, 2.0, 0.0), "LF2": (2.10, 2.0, 0.0), "LF3": (2.15, 2.0, 0.0)})
    assert ids(refine(field, base, ScriptedDispatch(near))) == ["LF1", "LF2", "LF3"]  # all within 0.15 of the leader
    clear = by_candidate(field, {"LF1": (2.0, 2.0, 0.0), "LF2": (2.10, 2.0, 0.0), "LF3": (2.4, 2.0, 0.0)})
    refined = refine(field, base, ScriptedDispatch(clear), reuse_cache=False)
    assert ids(refined) == ["LF3", "LF1", "LF2"] and refined["ordering_basis"] == "reading_history"
    assert refined["refinement"]["tie_band"] == 0.15


def test_total_failure_keeps_every_option_in_base_order_with_explicit_basis():
    field = make_field()
    base = options(field, "DEVELOP", REFINE_SCORES)
    refined = refine(field, base, ScriptedDispatch(lambda request: "error"))
    assert ids(refined) == ids(base) and [o["rank"] for o in refined["options"]] == [1, 2, 3]
    assert refined["ordering_basis"] == "base_assessments" and refined["refinement"]["state"] == "failed"
    assert refined["refinement"]["assessed_ids"] == [] and len(refined["refinement"]["errors"]) == 3
    assert all("simulated transport failure" in o["contextual_error"] and "contextual" not in o for o in refined["options"])

    def boom(request):
        raise RuntimeError("socket closed")

    raised = refine(field, base, boom)
    assert ids(raised) == ids(base) and raised["refinement"]["state"] == "failed"


def test_partial_failure_keeps_every_option_and_base_order():
    field = make_field()
    base = options(field, "DEVELOP", REFINE_SCORES)
    script = by_candidate(field, {"LF1": (1.0, 2.0, 0.0), "LF2": "error", "LF3": (3.0, 3.0, 0.0)})
    refined = refine(field, base, ScriptedDispatch(script))
    assert ids(refined) == ["LF1", "LF2", "LF3"]  # LF3 works far better, but one answer is missing: base order stands
    assert refined["ordering_basis"] == "base_assessments" and refined["refinement"]["state"] == "partial"
    assert refined["refinement"]["assessed_ids"] == ["LF1", "LF3"]
    by_id = {o["destination_id"]: o for o in refined["options"]}
    assert "contextual_error" in by_id["LF2"] and "contextual" not in by_id["LF2"]
    assert by_id["LF3"]["contextual"]["answers"]["works_after_history"]["score"] == 3.0
    assert [e["destination_id"] for e in refined["refinement"]["errors"]] == ["LF2"]


def test_mode_mismatch_is_an_error_and_is_never_reused():
    field = make_field()
    base = options(field, "DEVELOP", REFINE_SCORES)
    wrong = refine(field, base, ScriptedDispatch(mode="mock"), mode="live")
    assert wrong["refinement"]["state"] == "failed" and wrong["ordering_basis"] == "base_assessments"
    assert all("mode" in o["contextual_error"] for o in wrong["options"])
    live = ScriptedDispatch(mode="live")
    again = refine(field, base, live, mode="live")
    assert len(live.requests) == 3 and again["refinement"]["cache_hits"] == 0 and again["refinement"]["state"] == "ok"


def test_cache_is_reused_only_for_the_same_memory():
    field = make_field()
    base = options(field, "DEVELOP", REFINE_SCORES)
    dispatch = ScriptedDispatch()
    first = refine(field, base, dispatch)
    same = refine(field, base, dispatch)
    assert first["refinement"]["requests_dispatched"] == 3 and same["refinement"]["cache_hits"] == 3
    assert all(o["contextual"]["from_cache"] for o in same["options"]) and len(dispatch.requests) == 3
    longer = EVENTS[:1] + [ev("page_viewed", "LF6", via="dropdown"), EVENTS[1]]
    other = refine(field, base, dispatch, events=longer)
    assert other["refinement"]["cache_hits"] == 0 and len(dispatch.requests) == 6
    assert other["refinement"]["memory_sha256"] != first["refinement"]["memory_sha256"]
    assert refine(field, base, dispatch, reuse_cache=False)["refinement"]["requests_dispatched"] == 3


def test_a_changed_page_is_not_refined_but_options_stay():
    field = make_field()
    base = options(field, "DEVELOP", REFINE_SCORES)
    stale = {**copy.deepcopy(base), "page_sha256": "0" * 64}
    dispatch = ScriptedDispatch()
    refined = refine(field, stale, dispatch)
    assert ids(refined) == ids(base) and refined["refinement"]["state"] == "failed" and not dispatch.requests


# --------------------------------------------------------------------------- cli


def _parser():
    parser = argparse.ArgumentParser()
    cli.register_cli(parser.add_subparsers(dest="command", required=True))
    return parser


def test_cli_operator_options_and_coverage(monkeypatch, capsys):
    field = make_field()
    monkeypatch.setattr(cli, "load_field", lambda field_id: field)
    monkeypatch.setattr(oo, "_default_atlas_config_provider", atlas_config)
    monkeypatch.setattr(oo, "_default_profiles_provider",
                        lambda source, mode: make_rows(field, source, {"LF2": {"development": 0.9}}))
    args = _parser().parse_args(["operator-options", "PR2", "develop", "--mode", "mock"])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "state=options" in out and "1. LF2" in out and "Supported" in out and EXPLORATORY_LABEL in out
    assert len(out.splitlines()) == 4

    args = _parser().parse_args(["operator-coverage", "--mode", "mock", "--policy", "include-adjacent"])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "DEVELOP    18/18 pages show >=3" in out and "result: OK" in out and len(out.splitlines()) == 6

    # an atlas with holes: a page with >=3 eligible destinations shows fewer than 3 -> exit 1, with the reason
    monkeypatch.setattr(oo, "_default_profiles_provider",
                        lambda source, mode: make_rows(field, source, {}, default_status="unassessed" if source == "P1" else "complete"))
    args = _parser().parse_args(["operator-coverage", "--mode", "mock"])
    assert args.func(args) == 1
    out = capsys.readouterr().out
    assert "P1: 0 shown, 16 eligible, no_usable_profiles (unusable: unassessed)" in out and "result: FAIL (4 combination" in out
