from __future__ import annotations

import argparse
import json
import threading

import pytest

from gibsey_lab import recorder, scoring
from gibsey_lab.atlas import api, choice_history, cli, rubrics, store
from gibsey_lab.relational_operators import V0_1_CRITERIA, V0_2_CRITERIA

from test_atlas_support import LIVE_MODEL, atlas_env, fake_live  # noqa: F401


# ------------------------------------------------------------------ store


def test_reader_skips_corrupt_lines_and_reports_the_count(atlas_env):
    api.build_missing(scoring.mock_dispatch, "mock", pairs=[("P1", "P2")])
    with open(store.ASSESSMENTS_PATH, "a") as f:
        f.write("{not json at all\n")
        f.write(json.dumps({"schema": "something-else/1"}) + "\n")
    api.build_missing(scoring.mock_dispatch, "mock", pairs=[("P1", "P3")])
    with open(store.ASSESSMENTS_PATH, "a") as f:
        f.write('{"schema": "atlas-assessment/1", "half-written')  # no newline: a write in progress

    records, corrupt = store.read_assessments()
    assert [(r["source_id"], r["destination_id"]) for r in records] == [("P1", "P2"), ("P1", "P3")]
    assert corrupt == 2
    assert api.coverage("mock")["counts"]["complete"] == 2 and api.coverage("mock")["corrupt_lines_skipped"] == 2


def test_store_refuses_records_that_are_not_layer_one_assessments(atlas_env):
    api.build_missing(scoring.mock_dispatch, "mock", pairs=[("P1", "P2")])
    (good,), _ = store.read_assessments()

    with pytest.raises(store.StoreError):
        store.append_assessment({**good, "dimensions": {**good["dimensions"], "choice_probability": {"score": 0.4}}})
    with pytest.raises(store.StoreError):
        store.append_assessment({**good, "mode": "recorded"})
    with pytest.raises(store.StoreError):
        store.append_assessment({k: v for k, v in good.items() if k != "state"})
    with pytest.raises(store.StoreError):
        store.append_assessment({**good, "destination_id": good["source_id"]})
    assert len(store.read_assessments()[0]) == 1


def test_build_record_refuses_text_that_does_not_match_the_manifest_hash(atlas_env):
    source, destination = atlas_env.manifest["P1"], atlas_env.manifest["P2"]
    request = rubrics.build_pair_request("some other text", destination, "m")
    with pytest.raises(store.StoreError):
        store.build_record(job_id="j", source=source, destination=destination, rubric_version=rubrics.RUBRIC_VERSION,
                           config_id="cfg-x", request=request, outcome=scoring.mock_dispatch(request))


def test_concurrent_appends_produce_whole_lines(atlas_env):
    api.build_missing(scoring.mock_dispatch, "mock", pairs=[("P1", "P2")])
    (template,), _ = store.read_assessments()

    def writer(n):
        for i in range(25):
            store.append_assessment({**template, "assessment_id": f"as-{n}-{i}"})

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    records, corrupt = store.read_assessments()
    assert len(records) == 101 and corrupt == 0 and len({r["assessment_id"] for r in records}) == 101


# ------------------------------------------------------------------ Layer 2 choice history


def _write_run(run_id, *, source_id, option_order, probabilities, choice, reader_state, criterion,
               live=True, returned_model="jev-1.13.0", active_id=None, error=None):
    run_dir = recorder.RUNS_DIR / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "input.json").write_text(json.dumps({
        "run_id": run_id, "source_id": source_id, "active_id": active_id, "criterion": criterion,
        "option_order": option_order, "options": {}, "reader_state": reader_state, "corpus_hashes": {},
    }))
    (run_dir / "response.json").write_text(json.dumps({
        "live": live, "requested_model": "jev-latest", "returned_model": returned_model, "choice": choice,
        "confidence": 0.5, "probabilities": probabilities, "usage": {}, "error": error,
    }))


@pytest.fixture
def saved_runs(atlas_env):
    _write_run(  # a reader run: everything recorded
        "20260920T100000Z_reader-full-41-PR1-develop-v0.2-discovery_live", source_id="PR1",
        option_order=["PR3", "PR4", "LF2", "NONE"], probabilities={"PR3": 0.1, "PR4": 0.7, "LF2": 0.05, "NONE": 0.15},
        choice="PR4", criterion=V0_2_CRITERIA["DEVELOP"],
        reader_state={"app": "reader", "field": "full-41", "operator": "DEVELOP", "policy": "discovery", "criteria_version": "v0.2"},
    )
    _write_run(  # a legacy holdout experiment: no field / policy / version recorded
        "20260920T002226Z_relop-holdout-full-PR1-echo_live", source_id="PR1",
        option_order=["PR2", "PR4", "LF1", "NONE"], probabilities={"PR2": 0.6, "PR4": 0.3, "LF1": 0.0, "NONE": 0.1},
        choice="PR2", criterion=V0_1_CRITERIA["ECHO"], reader_state={"operator": "ECHO", "corpus": "holdout-LF-PR"},
    )
    _write_run(  # a tournament: few candidates, no NONE
        "20260919T233606Z_relop-tournament-PR1-echo_live", source_id="PR1", option_order=["PR4", "PR5"],
        probabilities={"PR4": 0.2, "PR5": 0.8}, choice="PR5", criterion=V0_1_CRITERIA["ECHO"],
        reader_state={"task": "operator-conditioned-destination-tournament", "operator": "ECHO"},
    )
    _write_run(  # reverse operator typing for one pair
        "20260919T231557Z_relop-reverse-PR1-PR4_live", source_id="PR1->PR4",
        option_order=["ECHO", "DEVELOP", "CONTRADICT", "BRIDGE", "NONE"],
        probabilities={"ECHO": 0.06, "DEVELOP": 0.93, "CONTRADICT": 0.0, "BRIDGE": 0.01, "NONE": 0.0}, choice="DEVELOP",
        criterion="Choose exactly one relation.",
        reader_state={"task": "reverse-operator-typing", "source_page": "PR1", "destination_page": "PR4"},
    )
    _write_run(  # a mock run stays labeled as mock
        "20260919T195107Z_mock-PR1_mock", source_id="PR1", option_order=["PR4", "NONE"],
        probabilities={"PR4": 0.9, "NONE": 0.1}, choice="PR4", criterion="x", reader_state={}, live=False,
        returned_model="mock",
    )
    _write_run(  # sentence-level request: not a page pair
        "20260919T205545Z_f12-micro_live", source_id="F12", active_id="F12.S4", option_order=["F12.S1", "NONE"],
        probabilities={"F12.S1": 0.9, "NONE": 0.1}, choice="F12.S1", criterion="x", reader_state={},
    )
    _write_run(  # an errored run has no distribution
        "20260920T110000Z_reader-full-41-PR1-echo_error", source_id="PR1", option_order=["PR4", "NONE"],
        probabilities=None, choice=None, criterion="x", reader_state={"field": "full-41"}, error="Timeout",
    )
    (recorder.RUNS_DIR / "relop-edges.csv").write_text("not,a,run\n")
    return atlas_env


def test_choice_rows_for_pair_carry_their_field_relative_provenance(saved_runs):
    rows = choice_history.choice_rows_for_pair("PR1", "PR4")
    assert [r["run_id"][:16] for r in rows] == sorted(r["run_id"][:16] for r in rows)  # oldest first
    assert {r["layer"] for r in rows} == {"field_relative_choice"} and len(rows) == 5
    by_run = {r["run_id"].split("_", 1)[1]: r for r in rows}

    reader = by_run["reader-full-41-PR1-develop-v0.2-discovery_live"]
    assert (reader["field"], reader["field_inferred"], reader["policy"], reader["criteria_version"]) == ("full-41", False, "discovery", "v0.2")
    assert (reader["operator"], reader["candidate_count"], reader["had_none_option"]) == ("DEVELOP", 3, True)
    assert (reader["probability"], reader["selected"], reader["live"]) == (0.7, True, True)
    assert (reader["requested_model"], reader["returned_model"]) == ("jev-latest", "jev-1.13.0")

    legacy = by_run["relop-holdout-full-PR1-echo_live"]
    assert (legacy["field"], legacy["field_inferred"]) == ("holdout-21", True)
    assert (legacy["policy"], legacy["criteria_version"]) == ("legacy-unrecorded", "v0.1")
    assert (legacy["probability"], legacy["selected"]) == (0.3, False)

    tournament = by_run["relop-tournament-PR1-echo_live"]
    assert (tournament["candidate_count"], tournament["had_none_option"], tournament["selected"]) == (2, False, False)

    reverse = by_run["relop-reverse-PR1-PR4_live"]
    assert reverse["row_kind"] == "reverse_operator_typing" and reverse["probability"] is None
    assert reverse["selected_operator"] == "DEVELOP" and reverse["operator_probabilities"]["DEVELOP"] == 0.93

    assert by_run["mock-PR1_mock"]["live"] is False
    assert choice_history.choice_rows_for_pair("PR4", "PR1") == []  # direction matters here too
    assert choice_history.choice_rows_for_pair("F12", "F12.S1") == []


def test_choice_rows_for_source_lists_every_competing_candidate(saved_runs):
    rows = choice_history.choice_rows_for_source("PR1")
    assert len(rows) == 3 + 3 + 2 + 1 + 1
    assert {r["destination_id"] for r in rows} == {"PR2", "PR3", "PR4", "PR5", "LF1", "LF2"}
    assert all(r["layer"] == "field_relative_choice" and "dimensions" not in r for r in rows)


def test_choice_history_never_becomes_a_dimension_or_a_profile(saved_runs):
    runs_before = {p.name: p.stat().st_mtime_ns for p in recorder.RUNS_DIR.rglob("*")}
    assert api.pair_status("PR1", "PR4", "live")["status"] == "unassessed"
    assert {r["status"] for r in api.profiles_for_source("PR1", "live")} == {"unassessed"}
    assert api.coverage("live")["counts"]["unassessed"] == 1640

    api.build_missing(fake_live(), "live", pairs=[("PR1", "PR4")])
    status = api.pair_status("PR1", "PR4", "live")
    assert status["layer"] == "base_pair_profile" and set(status["dimensions"]) == set(rubrics.DIMENSIONS)
    record_text = json.dumps(status["record"])
    assert "field_relative_choice" not in record_text and "0.93" not in record_text
    assert not store.ASSESSMENTS_PATH.read_text().count("reader-full-41")
    choice_history.choice_rows_for_source("PR1")
    assert {p.name: p.stat().st_mtime_ns for p in recorder.RUNS_DIR.rglob("*")} == runs_before  # runs/ is read-only


# ------------------------------------------------------------------ CLI


def _parser():
    parser = argparse.ArgumentParser()
    cli.register_cli(parser.add_subparsers(dest="command", required=True))
    return parser


def _run(argv) -> int:
    args = _parser().parse_args(argv)
    return args.func(args)


def test_cli_mock_build_inspect_coverage_and_resume(saved_runs, capsys):
    assert _run(["atlas-build", "--mock", "--pairs", "PR1:PR4,PR4:PR1"]) == 0
    out = capsys.readouterr().out
    assert "MOCK" in out and "attempted 2: ok 2" in out

    assert _run(["atlas-inspect", "PR1", "PR4", "--mode", "mock"]) == 0
    out = capsys.readouterr().out
    assert "status: COMPLETE" in out and "authored neighbor: no" in out
    for dim in rubrics.DIMENSIONS:
        assert dim in out
    layer1, layer2 = out.split("Layer 2 -- field-relative Choice history")
    assert "p=0.70" in layer2 and "p=0.70" not in layer1 and "not pair scores" in layer2
    assert len(out.splitlines()) < 40

    assert _run(["atlas-inspect", "PR1", "PR2", "--mode", "live"]) == 0
    out = capsys.readouterr().out
    assert "UNASSESSED" in out and "NOT a score of zero" in out and "authored neighbor: yes (next" in out

    assert _run(["atlas-coverage", "--mode", "mock"]) == 0
    out = capsys.readouterr().out
    assert "complete: 2" in out and "unassessed: 1638" in out and len(out.splitlines()) < 20
    assert _run(["atlas-coverage"]) == 0
    assert "NOT a complete live atlas" in capsys.readouterr().out

    assert _run(["atlas-resume", "--limit", "5"]) == 0
    out = capsys.readouterr().out
    assert "mock" in out and "skipped (already complete) 2" in out and "attempted 5" in out
    assert _run(["atlas-inspect", "NOPE", "PR1"]) == 1


def test_cli_live_build_needs_the_lead_wired_factory(atlas_env, capsys, monkeypatch):
    assert _run(["atlas-build", "--live", "--limit", "1"]) == 1
    assert "lead-wired" in capsys.readouterr().err
    assert not store.ASSESSMENTS_PATH.exists()

    monkeypatch.setattr(cli, "LIVE_DISPATCH_FACTORY", lambda: fake_live())
    assert _run(["atlas-build", "--live", "--pairs", "F12:P8", "--pinned-model", LIVE_MODEL]) == 0
    assert "LIVE" in capsys.readouterr().out
    assert api.pair_status("F12", "P8", "live")["status"] == "complete"
    with pytest.raises(SystemExit):
        _parser().parse_args(["atlas-build"])  # --mock or --live is required
    assert _run(["atlas-resume", "--limit", "2"]) == 0  # resume follows the last job's mode (live) via the factory
    assert api.coverage("live")["counts"]["complete"] == 3 and api.coverage("mock")["counts"]["complete"] == 0
