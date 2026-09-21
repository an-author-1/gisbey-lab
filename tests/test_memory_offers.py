import json

import pytest

from gibsey_lab.memory import contextual, offers, packet as pk, shortlist as sl
from gibsey_lab.scoring import mock_dispatch
from test_memory_helpers import ScriptedDispatch, atlas_config, by_candidate, ev, make_field, make_rows

STRONG = {
    "LF2": {"contradiction": 1.0}, "LF3": {"contradiction": 0.8}, "PR5": {"development": 0.9},
    "PR6": {"development": 0.7, "echo": 0.6}, "P1": {"bridge_relation": 0.67}, "LF5": {"echo": 0.9},
}


@pytest.fixture(autouse=True)
def stores(tmp_path, monkeypatch):
    monkeypatch.setattr(contextual, "ASSESSMENTS_PATH", tmp_path / "contextual" / "assessments.jsonl")
    monkeypatch.setattr(offers, "OFFER_SETS_PATH", tmp_path / "contextual" / "offer_sets.jsonl")
    return tmp_path


def run(field, dispatch, *, scores=STRONG, events=(), page="PR2", policy="discovery", rows=None, **kw):
    rows = rows if rows is not None else make_rows(field, page, scores)
    kw.setdefault("mode", "mock")
    return offers.build_offers(field, page, list(events), policy=policy, dispatch=dispatch, requested_model="jev-test",
                               profiles_provider=lambda source, mode: rows, atlas_config_provider=atlas_config, **kw)


def test_pipeline_records_every_step_and_offers_at_most_three():
    field = make_field()
    dispatch = ScriptedDispatch()
    events = [ev("page_viewed", "PR1", via="dropdown"), ev("page_viewed", "PR2", via="prev_next")]
    result = run(field, dispatch, events=events)
    assert result["schema"] == "offer-result/1" and result["state"] == "offers" and result["mode"] == "mock"
    assert result["page_sha256"] == field.manifest["PR2"].sha256 and result["policy"] == "discovery"
    assert result["base_counts"]["eligible"] == 15 and result["base_counts"]["ineligible_policy"] == 2
    shortlisted = [e["destination_id"] for e in result["shortlist"]]
    assert shortlisted == ["LF2", "LF5", "PR5", "LF3", "PR6", "P1"]
    assert result["assessed_ids"] == shortlisted and len(dispatch.requests) == 6  # the shortlist only
    assert result["not_assessed_count"] == 15 - 6
    assert [o["destination_id"] for o in result["offers"]] == ["LF2", "LF5", "PR5"]  # equal answers: base tie-break
    assert len({o["destination_id"] for o in result["offers"]}) == len(result["offers"]) <= offers.MAX_OFFERS
    assert result["memory_packet"]["source"] == "session_log" and result["memory_sha256"] == pk.memory_sha256(result["memory_packet"])
    assert [e["page_id"] for e in result["memory_packet"]["encounters"]] == ["PR1"]
    assert result["versions"]["atlas_config_id"] == "cfg-mock" and result["versions"]["offer_policy"] == "offers-v2"
    assert result["usage"]["requests_dispatched"] == 6 and result["usage"]["input_tokens"] == 600
    ranked_out = [r for r in result["rejected"] if r["stage"] == "ranking"]
    assert [r["destination_id"] for r in ranked_out] == ["LF3", "PR6", "P1"]

    offer = result["offers"][0]
    assert offer["base"]["layer"] == "base_pair_profile" and set(offer["base"]["dimensions"]) == set(sl.ALL_DIMENSIONS)
    assert offer["contextual"]["layer"] == "history_conditioned" and offer["contextual"]["from_cache"] is False
    assert set(offer["contextual"]["answers"]) == set(contextual.QUESTION_IDS)
    assert offer["contextual_assessment_id"].startswith("ctx_") and offer["base"]["assessment_id"] == "atlas_PR2_LF2"
    assert offer["destination_sha256"] == field.manifest["LF2"].sha256 and len(offer["rank_reasons"]) == 4

    (persisted,) = [json.loads(line) for line in offers.OFFER_SETS_PATH.read_text().splitlines()]
    assert persisted["offer_set_id"] == result["offer_set_id"] and persisted["state"] == "offers"


def test_ranking_is_ordered_over_separate_answers_not_a_sum():
    field = make_field()
    script = by_candidate(field, {
        "LF2": (2.0, 3.0, 0.0),   # works level 2
        "PR5": (3.0, 2.0, 1.0),   # works level 3, grounded 2
        "LF3": (3.0, 3.0, 2.0),   # works level 3, grounded 3  -> first despite most repetition
        "PR6": (3.0, 2.0, 0.0),   # same levels as PR5 but less repetition -> ahead of PR5
        "P1": (1.0, 3.0, 0.0),    # works below floor
        "LF5": (3.0, 1.0, 0.0),   # grounded below floor
    })
    result = run(field, ScriptedDispatch(script))
    assert [o["destination_id"] for o in result["offers"]] == ["LF3", "PR6", "PR5"]
    assert "works_after_history level 3" in result["offers"][0]["rank_reasons"][0]
    rejected = {r["destination_id"]: r for r in result["rejected"]}
    assert "works_after_history" in rejected["P1"]["reasons"][0] and rejected["P1"]["stage"] == "qualification"
    assert "grounded_reading_effect" in rejected["LF5"]["reasons"][0]
    assert rejected["LF2"]["stage"] == "ranking"
    assert not any("interesting" in json.dumps(o) for o in result["offers"])


def test_floors_sit_at_rubric_level_two_and_an_exact_two_passes():
    assert offers.WORKS_FLOOR == offers.GROUNDED_FLOOR == 2 / 3 and offers.REPEATS_CEILING == 0.67

    def answers(works, grounded, repeats=0.0):
        return {qid: {"score": v, "score_norm": v / 3} for qid, v in zip(contextual.QUESTION_IDS, (works, grounded, repeats))}

    assert offers.qualify(answers(2.0, 2.0)) == []
    assert len(offers.qualify(answers(1.86, 1.86))) == 2  # ~0.62: cleared the v1 floor of 0.5, not v2
    assert "works_after_history" in offers.qualify(answers(1.99, 2.0))[0]


def test_never_padded_to_three_and_weak_relations_never_labeled():
    field = make_field()
    script = by_candidate(field, {"LF2": (3.0, 3.0, 0.0), "LF3": (3.0, 3.0, 3.0)}, default=(0.0, 0.0, 0.0))
    scores = {**STRONG, "LF2": {"contradiction": 1.0, "echo": 0.45, "development": 0.2}}
    result = run(field, ScriptedDispatch(script), scores=scores)
    assert result["state"] == "offers" and [o["destination_id"] for o in result["offers"]] == ["LF2"]
    assert result["offers"][0]["relation_labels"] == ["contradiction"]
    assert "repeats_recent_reading" in next(r for r in result["rejected"] if r["destination_id"] == "LF3")["reasons"][0]


def test_revisits_and_neighbors_are_not_banned():
    field = make_field()
    events = [ev("page_viewed", "LF2", via="dropdown"), ev("page_viewed", "PR2", via="dropdown")]
    result = run(field, ScriptedDispatch(), events=events, policy="include-adjacent",
                 scores={"LF2": {"echo": 0.9}, "PR3": {"development": 0.9}})
    assert {o["destination_id"] for o in result["offers"]} == {"LF2", "PR3"}
    assert next(o for o in result["offers"] if o["destination_id"] == "PR3")["is_authored_neighbor"] is True


def test_state_no_candidates():
    field = make_field({"PR": 3})
    dispatch = ScriptedDispatch()
    result = run(field, dispatch, scores={})
    assert result["state"] == "no_candidates" and result["base_counts"]["eligible"] == 0 and not dispatch.requests


def test_state_atlas_incomplete():
    field = make_field()
    dispatch = ScriptedDispatch()
    rows = make_rows(field, "PR2", STRONG, default_status="unassessed", statuses={"PR1": "complete", "LF2": "failed", "LF3": "stale"})
    result = run(field, dispatch, rows=rows)
    assert result["state"] == "atlas_incomplete" and not dispatch.requests and result["offers"] == []
    assert result["base_counts"]["eligible_complete"] == 0 and result["base_counts"]["ineligible_incomplete"] == 15
    assert result["base_counts"]["failed"] == 1 and result["base_counts"]["stale"] == 1 and result["not_assessed_count"] == 15


def test_stale_destination_hash_is_not_usable_even_if_labeled_complete():
    field = make_field()
    rows = make_rows(field, "PR2", {"LF2": {"contradiction": 1.0}})
    next(r for r in rows if r["destination_id"] == "LF2")["destination_sha256"] = "0" * 64
    result = run(field, ScriptedDispatch(), rows=rows)
    assert "LF2" not in [e["destination_id"] for e in result["shortlist"]] and result["state"] == "no_qualified"


def test_state_no_qualified_is_distinct_for_empty_shortlist_and_failed_thresholds():
    field = make_field()
    weak = run(field, ScriptedDispatch(), scores={})
    assert weak["state"] == "no_qualified" and weak["state_detail"] == "empty_shortlist" and weak["assessed_ids"] == []
    dispatch = ScriptedDispatch(lambda request: dict(zip(contextual.QUESTION_IDS, (1.0, 1.0, 0.0))))
    low = run(field, dispatch)
    assert low["state"] == "no_qualified" and low["state_detail"] == "none_cleared_thresholds"
    assert len(low["assessed_ids"]) == 6 and low["offers"] == [] and len(low["rejected"]) == 6


def test_state_error_when_every_request_fails_and_partial_failures_proceed():
    field = make_field()
    total = run(field, ScriptedDispatch(lambda request: "error"))
    assert total["state"] == "error" and total["assessed_ids"] == [] and len(total["errors"]) == 6
    assert total["not_assessed_count"] == 15 and total["offers"] == []

    partial = run(field, ScriptedDispatch(by_candidate(field, {"LF2": "error", "PR5": "error"})))
    assert partial["state"] == "offers" and [e["destination_id"] for e in partial["errors"]] == ["LF2", "PR5"]
    assert partial["assessed_ids"] == ["LF5", "LF3", "PR6", "P1"] and partial["not_assessed_count"] == 11
    assert [o["destination_id"] for o in partial["offers"]] == ["LF5", "LF3", "PR6"]


def test_unreadable_atlas_is_an_error_not_an_empty_result():
    field = make_field()

    def broken(source, mode):
        raise ImportError("no module named gibsey_lab.atlas")

    result = offers.build_offers(field, "PR2", [], policy="discovery", dispatch=ScriptedDispatch(), mode="mock",
                                 requested_model="m", profiles_provider=broken, atlas_config_provider=atlas_config)
    assert result["state"] == "error" and result["state_detail"] == "atlas_unreadable"


def test_second_run_is_labeled_from_cache_and_errors_are_retried():
    field = make_field()
    flaky = {"fail": True}

    def script(request):
        if flaky["fail"] and request.state["candidate_destination"]["text"] == field.manifest["LF2"].text:
            return "error"
        return dict(zip(contextual.QUESTION_IDS, (3.0, 2.0, 0.0)))

    dispatch = ScriptedDispatch(script)
    first = run(field, dispatch)
    flaky["fail"] = False
    second = run(field, dispatch)
    assert first["usage"] == {**first["usage"], "requests_dispatched": 6, "cache_hits": 0}
    assert second["usage"]["cache_hits"] == 5 and second["usage"]["requests_dispatched"] == 1  # only the error is re-asked
    by_id = {o["destination_id"]: o for o in second["offers"]}
    assert by_id["LF2"]["from_cache"] is False and by_id["LF5"]["from_cache"] is True
    assert by_id["LF5"]["contextual"]["from_cache"] is True and by_id["LF5"]["base"]["layer"] == "base_pair_profile"
    third = run(field, dispatch, reuse_cache=False)
    assert third["usage"]["cache_hits"] == 0 and third["usage"]["requests_dispatched"] == 6


def test_three_histories_same_candidate_three_request_hashes_everything_else_identical():
    field = make_field()
    rows = make_rows(field, "PR2", STRONG)
    eligible = field.eligible_candidate_ids("PR2", "discovery")
    fixed = sl.build_shortlist(rows, eligible, page_order=field.all_ids())
    dispatch = ScriptedDispatch()
    results = {}
    for name, path in (("a", ["PR1", "PR3", "PR2"]), ("b", ["LF3", "PR2"]), ("c", ["PR2"])):
        memory = pk.fixture_packet(field, path, candidate_policy="discovery")
        results[name] = run(field, dispatch, rows=rows, memory_override=memory, fixed_shortlist=fixed, persist=False)

    assert not offers.OFFER_SETS_PATH.exists()  # persist=False keeps fixtures out of the reader's offer sets
    orders = [[e["destination_id"] for e in r["shortlist"]] for r in results.values()]
    assert orders[0] == orders[1] == orders[2] == [e["destination_id"] for e in fixed["entries"]]
    assert all(r["memory_source"] == "demonstration_fixture" and r["shortlist_fixed"] for r in results.values())

    per_condition = [dispatch.requests[i * 6:(i + 1) * 6] for i in range(3)]
    for position in range(6):
        trio = [reqs[position] for reqs in per_condition]
        assert len({r.request_sha256() for r in trio}) == 3
        assert len({r.state["candidate_destination"]["text"] for r in trio}) == 1
        assert len({r.state["current_page"]["text"] for r in trio}) == 1
        assert trio[0].questions == trio[1].questions == trio[2].questions
        assert len({r.requested_model for r in trio}) == 1
    a_req, b_req, c_req = (reqs[0] for reqs in per_condition)
    assert field.manifest["PR1"].text in json.dumps(a_req.state) and field.manifest["PR3"].text in json.dumps(a_req.state)
    assert field.manifest["LF3"].text in json.dumps(b_req.state) and field.manifest["PR1"].text not in json.dumps(b_req.state)
    assert c_req.state["reading_history"]["encounters"] == []


def test_memory_override_for_another_page_is_refused():
    field = make_field()
    wrong = pk.fixture_packet(field, ["PR1", "PR3"], candidate_policy="discovery")
    with pytest.raises(ValueError):
        run(field, ScriptedDispatch(), memory_override=wrong)


def test_static_ranking_is_base_only_and_can_differ_from_the_history_conditioned_offers():
    field = make_field()
    # Base order is LF2, LF5, PR5, LF3, PR6, P1. History-conditioned answers put P1 first
    # and disqualify LF2, so the two rankings must differ in a known way.
    script = by_candidate(field, {"P1": (3.0, 3.0, 0.0), "LF2": (1.0, 3.0, 0.0)}, default=(2.0, 2.0, 0.0))
    result = run(field, ScriptedDispatch(script))
    static = result["static_base_only"]
    assert [s["destination_id"] for s in static] == ["LF2", "LF5", "PR5", "LF3", "PR6", "P1"]
    assert [s["would_offer"] for s in static] == [True, True, True, False, False, False]
    assert all(s["layer"] == "base_pair_profile" for s in static)
    assert result["state"] == "offers" and len(result["assessed_ids"]) == 6
    assert [o["destination_id"] for o in result["offers"]] == ["P1", "LF5", "PR5"]


def test_real_mock_dispatch_runs_the_pipeline_reproducibly():
    field = make_field()
    first = run(field, mock_dispatch)
    again = run(field, mock_dispatch, reuse_cache=False)
    # mock_dispatch is a pure function of the request, and every input here is synthetic and
    # fixed, so the outcome is pinned exactly (it says nothing about literary quality).
    assert first["state"] == again["state"] == "no_qualified" and first["state_detail"] == "none_cleared_thresholds"
    assert first["assessed_ids"] == again["assessed_ids"] == ["LF2", "LF5", "PR5", "LF3", "PR6", "P1"]
    assert first["offers"] == again["offers"] == [] and len(first["rejected"]) == 6
    assert first["versions"]["returned_models"] == ["mock-lexical-overlap-v1"]
    assert [a["answers"] for a in first["assessed"]] == [a["answers"] for a in again["assessed"]]


def test_atlas_is_not_imported_at_module_import_time():
    import subprocess
    import sys

    code = ("import sys; import gibsey_lab.memory.offers, gibsey_lab.memory.demo, gibsey_lab.memory.cli; "
            "sys.exit(any(m.startswith('gibsey_lab.atlas') for m in sys.modules))")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
