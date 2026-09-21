import json
import threading
import urllib.error
import urllib.request

import pytest

from gibsey_lab import relational_operators
from gibsey_lab.config import Config
from gibsey_lab.reader import server as reader_server
from gibsey_lab.reader.server import ApiError, Handlers


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Every test uses tmp_path for Q/R state and the session log -- the real project
    data/ directory is never touched. RUNS_DIR is left real by default so tests can read
    genuine historical saved results; tests that create fake/mock runs opt into
    `isolated_runs_dir` separately so they never write into the real runs/ directory."""
    monkeypatch.setattr(reader_server, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(reader_server, "SESSION_LOG_PATH", tmp_path / "session_log.jsonl")
    monkeypatch.setattr(reader_server, "OUTCOMES_PATH", tmp_path / "data" / "reader_outcomes.jsonl")
    monkeypatch.setattr(reader_server, "OFFER_SETS_PATH", tmp_path / "data" / "reader_offer_sets.jsonl")
    monkeypatch.setattr(reader_server, "DEMO_DIR", tmp_path / "demo")
    reader_server._LATEST_REQUEST.clear()


@pytest.fixture
def isolated_runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(reader_server, "RUNS_DIR", tmp_path / "runs")
    return tmp_path / "runs"


# --- read-only endpoints against real saved data (no new calls) ---

def test_get_fields_defaults_to_full_41():
    data = Handlers.get_fields({})
    default = next(f for f in data["fields"] if f["default"])
    assert default["id"] == "full-41"
    assert {f["id"] for f in data["fields"]} == {"full-41", "holdout-21"}
    assert data["criteria"]["BRIDGE"] == relational_operators.CRITERIA["BRIDGE"]


def test_field_status_full_41_reports_no_problems():
    data = Handlers.get_field_status({"field": ["full-41"]})
    assert data["ok"] is True
    assert data["problems"] == []


def test_get_pages_full_41_has_41_grouped_by_text_numeric_within_group():
    data = Handlers.get_pages({"field": ["full-41"]})
    assert len(data["pages"]) == 41
    titles = [g["title"] for g in data["groups"]]
    assert titles == [
        "an author's preface",
        "The Foreword to the Foreword to an author's preface",
        "London Fox Who Vertically Disintegrates",
        "Princhetta Who Thinks Herself Alive",
    ]
    p_group = next(g for g in data["groups"] if g["prefix"] == "P")
    assert p_group["pages"] == [f"P{i}" for i in range(1, 9)]  # numeric order within group
    lf_group = next(g for g in data["groups"] if g["prefix"] == "LF")
    assert lf_group["pages"][0] == "LF1" and lf_group["pages"][-1] == "LF16"


def test_get_pages_holdout_still_available_and_has_21():
    data = Handlers.get_pages({"field": ["holdout-21"]})
    assert len(data["pages"]) == 21
    assert {g["prefix"] for g in data["groups"]} == {"LF", "PR"}


@pytest.mark.parametrize("source_id", ["P1", "F1", "LF1", "PR1"])
def test_every_prefix_gets_exactly_40_candidates_plus_none_in_full_field(source_id):
    """Under Include-adjacent (no neighbor exclusion), every source gets all 40 other
    pages regardless of its own text's prefix."""
    from gibsey_lab.fields import FULL_41, INCLUDE_ADJACENT, load_field
    from gibsey_lab.reader_context import assemble_reader_packet

    field = load_field(FULL_41)
    packet = assemble_reader_packet(field, source_id, "ECHO", policy=INCLUDE_ADJACENT)
    assert len(packet.option_order) == 41  # 40 other pages + NONE
    assert source_id not in packet.options
    assert "NONE" in packet.options


def test_get_page_includes_prev_next_neighbors():
    data = Handlers.get_page({"field": ["holdout-21"], "id": ["LF6"]})
    assert data["previous_id"] == "LF5"
    assert data["next_id"] == "LF7"


def test_get_page_pr1_full_text_matches_manifest():
    from gibsey_lab.fields import load_field

    data = Handlers.get_page({"field": ["holdout-21"], "id": ["PR1"]})
    field = load_field("holdout-21")
    assert data["text"] == field.manifest["PR1"].text
    assert data["sha256"] == field.manifest["PR1"].sha256


def test_get_saved_result_pr1_develop_is_recorded_pr4():
    """The historical Phase-A run used v0.1 wording and an unrestricted candidate set --
    explicitly requesting that exact configuration finds it."""
    data = Handlers.get_saved_result({
        "field": ["holdout-21"], "source": ["PR1"], "operator": ["DEVELOP"],
        "version": ["v0.1"], "policy": ["include-adjacent"],
    })
    assert data["recorded"] is True
    assert data["kind"] == "recorded"
    assert data["selected_id"] == "PR4"
    assert data["is_abstention"] is False


def test_get_saved_result_defaults_to_v0_2_discovery_which_has_no_recorded_history_yet():
    data = Handlers.get_saved_result({"field": ["holdout-21"], "source": ["PR1"], "operator": ["DEVELOP"]})
    assert data["recorded"] is False


def test_get_saved_result_never_preloads_for_expanded_field_with_no_history(isolated_runs_dir):
    """A field with no recorded runs preloads nothing. Asserted against an empty tmp runs
    dir: the real runs/ directory legitimately gains v0.2/discovery history over time."""
    data = Handlers.get_saved_result({"field": ["full-41"], "source": ["PR1"], "operator": ["DEVELOP"]})
    assert data["recorded"] is False


def test_get_saved_result_missing_params_is_api_error():
    with pytest.raises(ApiError):
        Handlers.get_saved_result({"field": ["holdout-21"]})


def test_a_holdout_result_is_never_conflated_with_a_full_41_result():
    """Same source/operator/version/policy, different field -- both fields happen to have
    their own genuine recorded result for this exact pair (holdout-21 from the original
    experiment, full-41 from a real reader session), and each must report its own field
    and its own actual destination rather than one leaking into the other."""
    params = {
        "source": ["PR1"], "operator": ["DEVELOP"],
        "version": ["v0.1"], "policy": ["include-adjacent"],
    }
    holdout_data = Handlers.get_saved_result({"field": ["holdout-21"], **params})
    full_data = Handlers.get_saved_result({"field": ["full-41"], **params})
    assert holdout_data["recorded"] is True and holdout_data["field"] == "holdout-21"
    assert full_data["recorded"] is True and full_data["field"] == "full-41"
    assert holdout_data["selected_id"] != full_data["selected_id"]  # genuinely distinct results, not the same record


def test_a_result_never_recorded_under_one_field_stays_absent_there(isolated_runs_dir):
    """Confirms the negative case where no genuine record exists (empty tmp runs dir --
    never an assertion about what the real runs/ directory happens to hold today)."""
    params = {"source": ["PR1"], "operator": ["DEVELOP"]}  # defaults: v0.2, discovery
    holdout_data = Handlers.get_saved_result({"field": ["holdout-21"], **params})
    full_data = Handlers.get_saved_result({"field": ["full-41"], **params})
    assert holdout_data["recorded"] is False
    assert full_data["recorded"] is False


# --- proposal vs. traversal: requesting/viewing must never move the reader ---

def _write_fake_run(base_dir, run_id="fake_run", selected_id="PR4", is_abstention=False, source_id="PR1",
                    field_id="full-41", policy="include-adjacent"):
    """A recorded-run directory shaped like recorder.record_run's output, carrying the
    real current page hashes so follow-time validation has something true to check."""
    from gibsey_lab.fields import load_field

    field = load_field(field_id)
    run_dir = base_dir / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "input.json").write_text(json.dumps({
        "run_id": run_id, "case_id": "reader-holdout-21-pr1-develop",
        "source_id": source_id, "active_id": None,
        "reader_state": {"app": "reader", "field": field_id, "operator": "DEVELOP", "policy": policy,
                         "criteria_version": "v0.2"},
        "corpus_hashes": {pid: page.sha256 for pid, page in field.manifest.items()},
    }))
    (run_dir / "result.json").write_text(json.dumps({
        "is_abstention": is_abstention,
        "selected_id": None if is_abstention else selected_id,
        "selected_text": None if is_abstention else "destination text",
        "confidence": 0.5,
    }))
    return run_dir


def test_cross_collection_destination_can_be_displayed_and_followed(isolated_runs_dir, tmp_path):
    """A source from one authored text (training corpus P) reaching a destination in a
    different text (holdout LF) must be followable like any other pairing -- the field
    does not restrict destinations to the source's own collection."""
    run_dir = _write_fake_run(tmp_path / "runs", source_id="P1", selected_id="LF1")
    outcome = Handlers.post_accept_and_follow({
        "run_dir": str(run_dir), "field": "full-41", "source": "P1", "operator": "BRIDGE", "from_page": "P1",
    })
    assert outcome["reader_state"]["active_passage"] == "LF1"


def test_previewing_a_saved_result_does_not_move_the_reader():
    before = Handlers.get_reader_state({})
    Handlers.get_saved_result({"field": ["holdout-21"], "source": ["PR1"], "operator": ["DEVELOP"]})
    after = Handlers.get_reader_state({})
    assert before == after


def test_propose_alone_does_not_move_reader(tmp_path, isolated_runs_dir):
    run_dir = _write_fake_run(tmp_path / "runs")
    before = Handlers.get_reader_state({})
    assert before["active_page"] is None

    result = Handlers.post_propose({"run_dir": str(run_dir)})
    assert result["proposal_id"].startswith("prop_")

    after = Handlers.get_reader_state({})
    assert after == before  # proposing must not move the reader


def test_accept_alone_does_not_move_reader(tmp_path, isolated_runs_dir):
    run_dir = _write_fake_run(tmp_path / "runs")
    proposal_id = Handlers.post_propose({"run_dir": str(run_dir)})["proposal_id"]
    before = Handlers.get_reader_state({})

    Handlers.post_accept({"proposal_id": proposal_id})

    after = Handlers.get_reader_state({})
    assert after == before  # accepting must not move the reader either


def test_follow_moves_the_reader(tmp_path, isolated_runs_dir):
    run_dir = _write_fake_run(tmp_path / "runs")
    proposal_id = Handlers.post_propose({"run_dir": str(run_dir)})["proposal_id"]
    bond_id = Handlers.post_accept({"proposal_id": proposal_id})["bond_id"]

    with pytest.raises(ApiError, match="from_page"):
        Handlers.post_follow({"bond_id": bond_id})  # the page being followed FROM is required
    assert Handlers.get_reader_state({})["history"] == []

    result = Handlers.post_follow({"bond_id": bond_id, "from_page": "PR1"})
    assert result["active_passage"] == "PR4"

    after = Handlers.get_reader_state({})
    assert after["active_passage"] == "PR4"
    assert len(after["history"]) == 1

    replay = Handlers.post_follow({"bond_id": bond_id, "from_page": "PR1"})
    assert replay["duplicate"] is True and len(replay["history"]) == 1  # a replay is never a second traversal


def test_accept_and_follow_records_all_three_as_separate_events_and_logs_a_traversal(tmp_path, isolated_runs_dir):
    run_dir = _write_fake_run(tmp_path / "runs")
    outcome = Handlers.post_accept_and_follow({
        "run_dir": str(run_dir), "field": "full-41", "source": "PR1", "operator": "DEVELOP", "from_page": "PR1",
    })
    assert outcome["proposal_id"].startswith("prop_")
    assert outcome["bond_id"].startswith("bond_")
    assert outcome["reader_state"]["active_passage"] == "PR4"

    proposals = json.loads((tmp_path / "data" / "proposals.json").read_text())
    bonds = json.loads((tmp_path / "data" / "bonds.json").read_text())
    reader_state = json.loads((tmp_path / "data" / "reader_state.json").read_text())
    assert len(proposals) == 1 and len(bonds) == 1
    assert reader_state["history"][0]["event"] == "Q_follow"

    from gibsey_lab import session_log

    events = session_log.read_events(log_path=tmp_path / "session_log.jsonl")
    traversals = [e for e in events if e["event"] == "accept_and_follow"]
    assert len(traversals) == 1
    assert traversals[0]["destination"] == "PR4"
    assert traversals[0]["field"] == "full-41"


def test_cannot_propose_from_abstained_run(tmp_path, isolated_runs_dir):
    run_dir = _write_fake_run(tmp_path / "runs", is_abstention=True)
    with pytest.raises(ApiError):
        Handlers.post_propose({"run_dir": str(run_dir)})


# --- repeat-safe preservation, kept separate from session recording ---

def test_preserve_is_repeat_safe_and_logged_separately_from_traversal(tmp_path, isolated_runs_dir):
    run_dir = _write_fake_run(tmp_path / "runs")
    outcome = Handlers.post_accept_and_follow({"run_dir": str(run_dir), "from_page": "PR1"})
    bond_id = outcome["bond_id"]

    entry1 = Handlers.post_preserve({"bond_id": bond_id})["entry_id"]
    entry2 = Handlers.post_preserve({"bond_id": bond_id})["entry_id"]
    assert entry1 == entry2

    index = json.loads((tmp_path / "data" / "gibsey_vault" / "index.json").read_text())
    assert len(index) == 1

    from gibsey_lab import session_log

    events = session_log.read_events(log_path=tmp_path / "session_log.jsonl")
    preserved_events = [e for e in events if e["event"] == "preserved"]
    traversal_events = [e for e in events if e["event"] == "accept_and_follow"]
    assert len(preserved_events) == 2  # both preserve clicks logged, even though repeat-safe
    assert len(traversal_events) == 1  # distinct from the one traversal event


# --- passive session navigation logging (no written notes required) ---

def test_session_navigation_logs_page_views_field_switches_and_back(tmp_path):
    Handlers.post_session_navigation({"event": "field_selected", "field": "full-41"})
    Handlers.post_session_navigation({"event": "page_viewed", "field": "full-41", "page_id": "P1"})
    Handlers.post_session_navigation({"event": "back", "field": "full-41", "from_page": "P1", "page_id": "F1"})

    from gibsey_lab import session_log

    events = session_log.read_events(log_path=tmp_path / "session_log.jsonl")
    assert [e["event"] for e in events] == ["field_selected", "page_viewed", "back"]


def test_session_navigation_rejects_unknown_event():
    with pytest.raises(ApiError):
        Handlers.post_session_navigation({"event": "not_a_real_event"})


# --- request-selection: a clearly labeled mock check of the live-call code path ---

def test_request_selection_wires_to_run_case_without_a_real_network_call(monkeypatch, tmp_path, isolated_runs_dir):
    """Monkeypatches the lowest real seam (jev_client.run_choice) so this exercises the
    exact same packet-assembly / runner / recorder pipeline a real request would, with
    no network access and no spend. This is the 'clearly labeled mock check' -- the
    live app never does this substitution."""
    from gibsey_lab import jev_client
    from gibsey_lab.results import ChoiceResult

    def fake_run_choice(cfg, *, state, instructions, criteria):
        assert "PR1" not in criteria  # source excluded from its own candidates
        return ChoiceResult(
            requested_model=cfg.model, returned_model="jev-1.13.0-mock-check",
            choice="PR4", confidence=0.42, probabilities={"PR4": 0.42}, live=True,
        )

    monkeypatch.setattr(jev_client, "run_choice", fake_run_choice)
    monkeypatch.setattr(reader_server, "load_config", lambda: Config(model="jev-latest", api_key="test-key-not-real"))

    record = Handlers.post_request_selection({"field": "holdout-21", "source": "PR1", "operator": "DEVELOP"})
    assert record["result"]["selected_id"] == "PR4"
    assert record["returned_model"] == "jev-1.13.0-mock-check"
    assert record["kind"] == "new"

    saved_run_dir = list((tmp_path / "runs").iterdir())[0]
    assert saved_run_dir.name.endswith("_reader-holdout-21-PR1-develop-v0.2-discovery_live")

    from gibsey_lab import session_log

    events = session_log.read_events(log_path=tmp_path / "session_log.jsonl")
    assert any(e["event"] == "operator_result" and e["kind"] == "new" for e in events)


def test_request_selection_requires_credentials(monkeypatch):
    monkeypatch.setattr(reader_server, "load_config", lambda: Config(model="jev-latest", api_key=None))
    with pytest.raises(ApiError):
        Handlers.post_request_selection({"field": "holdout-21", "source": "PR1", "operator": "ECHO"})


# --- optional review notes: never touch Jev input ---

def test_review_note_is_optional_and_separate_from_run_input(tmp_path, isolated_runs_dir):
    run_dir = _write_fake_run(tmp_path / "runs")
    (run_dir / "review.json").write_text(json.dumps({
        "correspondence": None, "reading_effect": None,
        "grounding_score": None, "effect_score": None, "decision": "undecided",
    }))
    review = Handlers.post_review({"run_dir": str(run_dir), "decision": "accept"})
    assert review["decision"] == "accept"

    # The recorded input for this run is untouched by the note.
    input_record = json.loads((run_dir / "input.json").read_text())
    assert "correspondence" not in json.dumps(input_record)


# --- one real end-to-end HTTP check: server binds locally, serves static + API ---

def test_server_binds_to_127_0_0_1_only():
    with pytest.raises(ValueError, match="localhost only"):
        reader_server.run(host="0.0.0.0", port=0, open_browser=False)


def test_full_http_roundtrip(tmp_path, monkeypatch):
    # DATA_DIR/SESSION_LOG_PATH isolated via the autouse fixture; RUNS_DIR is left real
    # here since this test checks a genuine historical saved-result over real HTTP.
    httpd = reader_server.ThreadingHTTPServer(("127.0.0.1", 0), reader_server.ReaderRequestHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            assert resp.status == 200
            assert b"Gibsey Lab Reader" in resp.read()

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/fields", timeout=5) as resp:
            data = json.loads(resp.read())
            assert data["fields"][0]["id"] == "full-41"

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/saved-result?field=holdout-21&source=PR1&operator=DEVELOP"
            f"&version=v0.1&policy=include-adjacent", timeout=5
        ) as resp:
            data = json.loads(resp.read())
            assert data["selected_id"] == "PR4"

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/propose",
            data=b"not json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "expected an HTTP error for invalid JSON"
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        httpd.shutdown()
        httpd.server_close()
