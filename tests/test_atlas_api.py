from __future__ import annotations

import json
from dataclasses import replace

import pytest

from gibsey_lab import scoring
from gibsey_lab.atlas import api, rubrics, store
from gibsey_lab.atlas.ledger import Ledger

from test_atlas_support import LIVE_MODEL, CountingDispatch, atlas_env, failing_live, fake_live, invalid_live  # noqa: F401


def _lines(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ------------------------------------------------------------------ the pair space


def test_41_pages_give_1640_directed_pairs_including_authored_neighbors(atlas_env):
    pairs = api.all_pairs()
    assert len(pairs) == 1640 == len(set(pairs))
    assert all(src != dst for src, dst in pairs)
    assert ("PR1", "PR2") in pairs and ("PR2", "PR1") in pairs  # immediate authored neighbors stay in
    assert ("F12", "P8") in pairs and ("P8", "F12") in pairs


def test_profiles_for_source_is_always_40_rows_with_neighbor_flags(atlas_env):
    rows = api.profiles_for_source("PR2", mode="mock")
    assert len(rows) == 40 and {r["status"] for r in rows} == {"unassessed"}
    assert all(r["dimensions"] is None and r["layer"] == "base_pair_profile" for r in rows)
    neighbors = {r["destination_id"]: r["neighbor_relation"] for r in rows if r["is_authored_neighbor"]}
    assert neighbors == {"PR1": "previous", "PR3": "next"}
    with pytest.raises(api.AtlasError):
        api.profiles_for_source("ZZ9")
    with pytest.raises(api.AtlasError):
        api.pair_status("P1", "P1")


def test_direction_is_distinct(atlas_env):
    api.build_missing(scoring.mock_dispatch, "mock", pairs=[("F12", "P8")])
    forward, backward = api.pair_status("F12", "P8", "mock"), api.pair_status("P8", "F12", "mock")
    assert forward["status"] == "complete" and backward["status"] == "unassessed"
    api.build_missing(scoring.mock_dispatch, "mock", pairs=[("P8", "F12")])
    backward = api.pair_status("P8", "F12", "mock")
    assert backward["status"] == "complete"
    assert forward["record"]["request_sha256"] != backward["record"]["request_sha256"]
    assert forward["record"]["state"]["source_page"] == backward["record"]["state"]["destination_page"]


# ------------------------------------------------------------------ statuses


def test_record_matches_the_contract_schema_and_keeps_what_was_sent(atlas_env):
    api.build_missing(scoring.mock_dispatch, "mock", pairs=[("LF1", "LF3")], job_id="job-x")
    (record,) = _lines(store.ASSESSMENTS_PATH)
    assert set(store.REQUIRED_KEYS) <= set(record)
    assert record["schema"] == "atlas-assessment/1" and record["job_id"] == "job-x" and record["mode"] == "mock"
    assert record["state"] == {"source_page": {"text": atlas_env.manifest["LF1"].text},
                               "destination_page": {"text": atlas_env.manifest["LF3"].text}}
    assert "LF1" not in json.dumps(record["questions"]) and [q["qid"] for q in record["questions"]] == list(rubrics.DIMENSIONS)
    assert record["source_sha256"] == atlas_env.manifest["LF1"].sha256
    assert record["rubric_version"] == rubrics.RUBRIC_VERSION
    assert record["config_id"] == api.active_config("mock")["config_id"]
    assert list(record["dimensions"]) == list(rubrics.DIMENSIONS)
    for value in record["dimensions"].values():
        assert {"score", "score_norm", "max_level", "confidence", "probabilities", "valid", "problems"} <= set(value)


def test_a_low_score_is_complete_not_missing(atlas_env):
    def all_zero(request):
        good = scoring.mock_dispatch(request)
        answers = {
            q.qid: scoring.validate_answer(q, {"type": "score", "score": 0.0, "confidence": 0.9,
                                               "probabilities": {"0": 1.0, "1": 0.0, "2": 0.0, "3": 0.0}})
            for q in request.questions
        }
        return replace(good, answers=answers)

    api.build_missing(all_zero, "mock", pairs=[("P1", "LF9")])
    rows = {r["destination_id"]: r for r in api.profiles_for_source("P1", "mock")}
    weak, missing = rows["LF9"], rows["LF8"]
    assert weak["status"] == "complete"
    assert {d: v["score"] for d, v in weak["dimensions"].items()} == {d: 0.0 for d in rubrics.DIMENSIONS}
    assert missing["status"] == "unassessed" and missing["dimensions"] is None  # missing is not zero


def test_failed_and_invalid_provider_responses_are_failed_not_complete(atlas_env):
    summary = api.build_missing(failing_live(), "live", pairs=[("P1", "P2")])
    assert (summary["error"], summary["ok"]) == (1, 0)
    summary = api.build_missing(invalid_live(), "live", pairs=[("P1", "P3")])
    assert (summary["invalid"], summary["ok"]) == (1, 0)

    errored, invalid = api.pair_status("P1", "P2"), api.pair_status("P1", "P3")
    assert errored["status"] == "failed" and errored["record"] is None and errored["dimensions"] is None
    assert "provider unreachable" in errored["last_errors"][0]
    assert invalid["status"] == "failed" and any("echo" in e for e in invalid["last_errors"])
    stored = invalid["latest_record"]
    assert stored["status"] == "invalid" and stored["dimensions"]["echo"]["valid"] is False
    assert stored["dimensions"]["development"]["valid"] is True  # the raw answers are all kept

    # A later good answer completes the pair; the failures stay in the file.
    api.build_missing(fake_live(), "live", pairs=[("P1", "P2"), ("P1", "P3")])
    assert api.pair_status("P1", "P2")["status"] == "complete"
    assert [r["status"] for r in _lines(store.ASSESSMENTS_PATH)] == ["error", "invalid", "ok", "ok"]


def test_editing_a_page_makes_its_pairs_stale_without_overwriting_history(atlas_env):
    pairs = [("P1", "P2"), ("P2", "P1"), ("P3", "P4")]
    api.build_missing(scoring.mock_dispatch, "mock", pairs=pairs)
    before = store.ASSESSMENTS_PATH.read_text()

    atlas_env.edit_page("P2", "P2 has been rewritten entirely.")
    assert api.pair_status("P1", "P2", "mock")["status"] == "stale"
    assert "destination text changed" in api.pair_status("P1", "P2", "mock")["stale_reasons"][0]
    assert api.pair_status("P2", "P1", "mock")["status"] == "stale"
    assert api.pair_status("P3", "P4", "mock")["status"] == "complete"
    assert store.ASSESSMENTS_PATH.read_text() == before

    dispatch = CountingDispatch(scoring.mock_dispatch)
    summary = api.build_missing(dispatch, "mock", pairs=pairs)
    assert dispatch.count == 2 and summary["skipped_complete"] == 1
    assert api.pair_status("P1", "P2", "mock")["status"] == "complete"
    text = store.ASSESSMENTS_PATH.read_text()
    assert text.startswith(before) and len(_lines(store.ASSESSMENTS_PATH)) == 5


def test_a_new_rubric_version_invalidates_without_overwriting(atlas_env, monkeypatch):
    api.build_missing(scoring.mock_dispatch, "mock", pairs=[("F1", "F2")])
    old_config = api.active_config("mock")["config_id"]
    before = store.ASSESSMENTS_PATH.read_text()

    v3 = rubrics.Rubric(version="atlas-rubric-v3-test", questions=tuple(
        replace(q, instructions=q.instructions + " (reworded)") for q in rubrics.get_rubric().questions))
    monkeypatch.setitem(rubrics.RUBRICS_BY_VERSION, v3.version, v3)
    monkeypatch.setattr(api, "RUBRIC_VERSION", v3.version)

    assert api.active_config("mock")["config_id"] != old_config
    status = api.pair_status("F1", "F2", "mock")
    assert status["status"] == "stale" and "rubric" in status["stale_reasons"][0]
    api.build_missing(scoring.mock_dispatch, "mock", pairs=[("F1", "F2")])
    assert api.pair_status("F1", "F2", "mock")["record"]["rubric_version"] == v3.version
    assert store.ASSESSMENTS_PATH.read_text().startswith(before)

    monkeypatch.setattr(api, "RUBRIC_VERSION", rubrics.RUBRIC_VERSION)  # the earlier records are still there, still valid
    assert api.pair_status("F1", "F2", "mock")["record"]["rubric_version"] == rubrics.RUBRIC_VERSION


def test_v1_pilot_records_become_stale_under_v2_and_are_never_deleted(atlas_env, monkeypatch):
    assert api.active_config("live")["rubric_version"] == "atlas-rubric-v2"
    assert api.compute_config_id("atlas-rubric-v1", LIVE_MODEL) != api.compute_config_id("atlas-rubric-v2", LIVE_MODEL)

    monkeypatch.setattr(api, "RUBRIC_VERSION", "atlas-rubric-v1")  # the pilot ran under v1
    pilot = [("F12", "P8"), ("P8", "F12")]
    api.build_missing(fake_live(), "live", pairs=pilot)
    assert api.coverage("live")["counts"]["complete"] == 2
    pilot_text = store.ASSESSMENTS_PATH.read_text()
    monkeypatch.setattr(api, "RUBRIC_VERSION", "atlas-rubric-v2")

    status = api.pair_status("F12", "P8")
    assert status["status"] == "stale" and status["dimensions"] is None
    assert status["stale_reasons"] == ["rubric atlas-rubric-v1 != active atlas-rubric-v2"]
    assert api.coverage("live")["counts"] == {"complete": 0, "stale": 2, "failed": 0, "unassessed": 1638}

    dispatch = CountingDispatch(fake_live())
    api.build_missing(dispatch, "live", pairs=pilot)
    assert dispatch.count == 2 and dispatch.requests[0].questions == rubrics.RUBRIC_V2.questions
    records = _lines(store.ASSESSMENTS_PATH)
    assert [r["rubric_version"] for r in records] == ["atlas-rubric-v1"] * 2 + ["atlas-rubric-v2"] * 2
    assert [q["qid"] for q in records[0]["questions"]] == list(rubrics.DIMENSIONS)
    assert records[0]["questions"][4]["levels"][0].startswith("No bridge:")  # the v1 wording sent stays on record
    assert store.ASSESSMENTS_PATH.read_text().startswith(pilot_text)
    assert api.pair_status("F12", "P8")["record"]["rubric_version"] == "atlas-rubric-v2"

    frozen = api.freeze_config(pinned_returned_model=LIVE_MODEL, requested_model="jev-latest")
    assert frozen["rubric_version"] == "atlas-rubric-v2" and api.coverage("live")["counts"]["complete"] == 2


def test_config_id_depends_on_rubric_wording_and_pinned_model(atlas_env):
    a = api.compute_config_id(rubrics.RUBRIC_VERSION, "jev-1")
    assert a == api.compute_config_id(rubrics.RUBRIC_VERSION, "jev-1")
    assert a != api.compute_config_id(rubrics.RUBRIC_VERSION, "jev-2")
    assert a != api.compute_config_id(rubrics.RUBRIC_VERSION, None)
    assert api.active_config("mock")["pinned_returned_model"] == scoring.MOCK_MODEL


# ------------------------------------------------------------------ freeze + models


def test_live_config_is_unfrozen_until_freeze_config_and_survives_a_pilot(atlas_env):
    cfg = api.active_config("live")
    assert cfg["frozen"] is False and cfg["pinned_returned_model"] is None
    api.build_missing(fake_live(), "live", pairs=[("PR1", "PR4"), ("PR4", "PR1")])  # pilot
    assert api.coverage("live")["counts"]["complete"] == 2
    assert api.coverage("live")["is_complete_live_atlas"] is False

    frozen = api.freeze_config(pinned_returned_model=LIVE_MODEL, requested_model="jev-latest", note="after pilot")
    assert frozen["frozen"] is True and frozen["pinned_returned_model"] == LIVE_MODEL
    assert api.active_config("live")["config_id"] == api.compute_config_id(rubrics.RUBRIC_VERSION, LIVE_MODEL)
    assert api.coverage("live")["counts"]["complete"] == 2  # pilot answers by the pinned model still count

    assert api.freeze_config(pinned_returned_model=LIVE_MODEL, requested_model="jev-latest")["frozen"]  # idempotent
    with pytest.raises(api.AtlasError):
        api.freeze_config(pinned_returned_model="jev-other", requested_model="jev-latest")
    api.freeze_config(pinned_returned_model="jev-other", requested_model="jev-latest", replace=True)
    assert json.loads(api.CONFIG_PATH.read_text())["history"][0]["pinned_returned_model"] == LIVE_MODEL
    assert api.coverage("live")["counts"] == {"complete": 0, "stale": 2, "failed": 0, "unassessed": 1638}


def test_returned_model_mismatch_is_recorded_but_never_pooled_and_stops_the_build(atlas_env):
    api.freeze_config(pinned_returned_model=LIVE_MODEL, requested_model="jev-latest")
    api.build_missing(fake_live(), "live", pairs=[("P1", "P2")])

    drifted = CountingDispatch(fake_live(returned_model="jev-10.0.0-drift"))
    pairs = [("P1", "P3"), ("P1", "P4"), ("P1", "P5"), ("P1", "P6"), ("P1", "P7")]
    summary = api.build_missing(drifted, "live", pairs=pairs, concurrency=1)
    assert summary["stopped_reason"] == "returned_model_mismatch" and drifted.count == 1
    assert summary["model_mismatch"] == 1 and summary["remaining"] == 5

    status = api.pair_status("P1", "P3")
    assert status["status"] == "stale" and status["dimensions"] is None
    assert "returned model jev-10.0.0-drift != pinned" in status["stale_reasons"][0]
    assert status["latest_record"]["config_id"] != api.active_config("live")["config_id"]
    cov = api.coverage("live")
    assert cov["counts"]["complete"] == 1 and cov["returned_models"] == [LIVE_MODEL]
    assert cov["returned_models_seen_in_store"] == sorted([LIVE_MODEL, "jev-10.0.0-drift"])

    with pytest.raises(api.AtlasError):  # a frozen config cannot be built against another model
        api.build_missing(fake_live(), "live", pairs=pairs, pinned_returned_model="jev-10.0.0-drift")


def test_frozen_config_also_pins_the_requested_model_without_changing_config_id(atlas_env):
    frozen = api.freeze_config(pinned_returned_model=LIVE_MODEL, requested_model="jev-1.2.3")
    config_id = frozen["config_id"]
    assert config_id == api.compute_config_id(rubrics.RUBRIC_VERSION, LIVE_MODEL)  # requested model is not in the id

    with pytest.raises(api.AtlasError):  # such records could never be complete: refuse before dispatching
        api.build_missing(fake_live(), "live", pairs=[("P1", "P2")], requested_model="jev-latest")
    assert not store.ASSESSMENTS_PATH.exists()

    api.build_missing(fake_live(), "live", pairs=[("P1", "P2"), ("P1", "P3")])
    good = api.pair_status("P1", "P2")["record"]
    assert good["requested_model"] == "jev-1.2.3" and good["config_id"] == config_id

    # Same config_id, same returned model, same hashes -- but it was requested as another model.
    store.append_assessment({**good, "assessment_id": "as-other-request", "destination_id": "P4",
                             "destination_sha256": atlas_env.manifest["P4"].sha256, "requested_model": "jev-latest"})
    status = api.pair_status("P1", "P4")
    assert status["status"] == "stale" and status["dimensions"] is None
    assert status["stale_reasons"] == ["requested model jev-latest != frozen jev-1.2.3"]
    assert api.coverage("live")["counts"] == {"complete": 2, "stale": 1, "failed": 0, "unassessed": 1637}

    dispatch = CountingDispatch(fake_live())
    api.build_missing(dispatch, "live", pairs=[("P1", "P2"), ("P1", "P4")])
    assert dispatch.count == 1 and api.pair_status("P1", "P4")["record"]["requested_model"] == "jev-1.2.3"


# ------------------------------------------------------------------ mock / live separation


def test_mock_records_never_count_toward_live_coverage(atlas_env):
    api.build_missing(scoring.mock_dispatch, "mock", pairs=[("LF1", "LF3"), ("LF3", "LF1")])
    assert api.coverage("mock")["counts"]["complete"] == 2
    live = api.coverage("live")
    assert live["counts"] == {"complete": 0, "stale": 0, "failed": 0, "unassessed": 1640}
    assert live["records_in_mode"] == 0 and live["returned_models"] == []
    assert api.pair_status("LF1", "LF3", "live")["status"] == "unassessed"
    assert {r["status"] for r in api.profiles_for_source("LF1", "live")} == {"unassessed"}

    api.build_missing(fake_live(), "live", pairs=[("LF1", "LF3")])
    assert api.coverage("live")["counts"]["complete"] == 1
    assert api.coverage("mock")["counts"]["complete"] == 2
    assert api.coverage("mock")["returned_models"] == [scoring.MOCK_MODEL]


@pytest.mark.parametrize("dispatch, requested", [(scoring.mock_dispatch, "live"), (fake_live(), "mock")])
def test_mode_mismatch_raises_and_writes_nothing(atlas_env, dispatch, requested):
    with pytest.raises(api.AtlasModeError):
        api.build_missing(dispatch, requested, pairs=[("P1", "P2"), ("P2", "P3")])
    assert not store.ASSESSMENTS_PATH.exists()
    assert api.coverage(requested)["counts"]["unassessed"] == 1640


# ------------------------------------------------------------------ build / resume


def test_full_mock_build_then_resume_dispatches_nothing(atlas_env):
    first = CountingDispatch(scoring.mock_dispatch)
    summary = api.build_missing(first, "mock", limit=100)
    assert first.count == 100 and summary["stopped_reason"] == "limit" and summary["remaining"] == 1540

    second = CountingDispatch(scoring.mock_dispatch)
    summary = api.build_missing(second, "mock")
    assert second.count == 1540 and summary["skipped_complete"] == 100
    assert summary["stopped_reason"] is None and summary["remaining"] == 0

    cov = api.coverage("mock")
    assert cov["total_pairs"] == 1640 and cov["counts"]["complete"] == 1640
    assert len(cov["per_source"]) == 41 and all(c["complete"] == 40 for c in cov["per_source"].values())
    assert cov["is_complete_live_atlas"] is False  # a complete mock atlas is never a live atlas

    third = CountingDispatch(scoring.mock_dispatch)
    summary = api.build_missing(third, "mock")
    assert third.count == 0 and summary["attempted"] == 0 and summary["skipped_complete"] == 1640
    assert len(_lines(store.ASSESSMENTS_PATH)) == 1640
    rows = api.profiles_for_source("PR2", "mock")
    assert len(rows) == 40 and all(r["status"] == "complete" and len(r["dimensions"]) == 7 for r in rows)


def test_resume_retries_failed_pairs_and_skips_complete_ones(atlas_env):
    pairs = [("F1", "F2"), ("F1", "F3"), ("F1", "F4")]
    api.build_missing(fake_live(), "live", pairs=pairs[:1])
    api.build_missing(failing_live(), "live", pairs=pairs[1:2])
    dispatch = CountingDispatch(fake_live())
    summary = api.build_missing(dispatch, "live", pairs=pairs)
    assert dispatch.count == 2 and summary["skipped_complete"] == 1 and summary["ok"] == 2
    assert api.last_job()["mode"] == "live"


def test_persistent_provider_failure_stops_boundedly(atlas_env):
    dispatch = CountingDispatch(failing_live())
    summary = api.build_missing(dispatch, "live", concurrency=1)
    assert summary["stopped_reason"] == "consecutive_errors"
    assert dispatch.count == api.MAX_CONSECUTIVE_FAILURES == summary["error"]
    cov = api.coverage("live")
    assert cov["counts"]["failed"] == api.MAX_CONSECUTIVE_FAILURES  # exact failed coverage is preserved
    assert cov["counts"]["unassessed"] == 1640 - api.MAX_CONSECUTIVE_FAILURES


def test_budget_refusal_stops_the_build_without_recording_an_assessment(atlas_env):
    ledger = Ledger(max_attempts=3)

    def ledgered(request):  # the shape of scoring.make_live_dispatch, minus the network
        rid = ledger.reserve(request_sha256=request.request_sha256(), kind=request.kind,
                             est_input_tokens=scoring.estimate_input_tokens(request))
        if rid is None:
            return scoring.ScoreOutcome("budget_refused", "live", request.requested_model, None, {}, None, 0.0, 0,
                                        ["budget ledger refused"], request.request_sha256())
        outcome = fake_live()(request)
        ledger.settle(rid, ok=True, usage=outcome.usage, returned_model=outcome.returned_model, error=None)
        return replace(outcome, ledger_ids=[rid])

    summary = api.build_missing(ledgered, "live", concurrency=1, pairs=api.all_pairs()[:10])
    assert summary["stopped_reason"] == "budget_refused"
    assert (summary["ok"], summary["attempted"], summary["remaining"]) == (3, 3, 7)
    assert len(_lines(store.ASSESSMENTS_PATH)) == 3 and ledger.summary()["attempts"] == 3
    assert _lines(store.ASSESSMENTS_PATH)[0]["ledger_ids"][0].startswith("res-")


def test_concurrency_is_capped_at_two(atlas_env):
    import threading
    import time

    active, peak, lock = [0], [0], threading.Lock()

    def slow(request):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.01)
        with lock:
            active[0] -= 1
        return scoring.mock_dispatch(request)

    api.build_missing(slow, "mock", limit=12, concurrency=8)
    assert peak[0] <= 2 and api.coverage("mock")["counts"]["complete"] == 12
