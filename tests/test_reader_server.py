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
def isolated_data_and_runs_dir(tmp_path, monkeypatch):
    """Every test in this file uses tmp_path for Q/R state and any run records it
    creates -- the real project data/ and runs/ directories are never touched."""
    monkeypatch.setattr(reader_server, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(reader_server, "RUNS_DIR", tmp_path / "runs")


# --- read-only endpoints against real saved data (no new calls) ---

def test_get_fields_defaults_to_holdout_21():
    data = Handlers.get_fields({})
    default = next(f for f in data["fields"] if f["default"])
    assert default["id"] == "holdout-21"
    assert data["criteria"]["BRIDGE"] == relational_operators.CRITERIA["BRIDGE"]


def test_get_pages_holdout_has_21():
    data = Handlers.get_pages({"field": ["holdout-21"]})
    assert len(data["pages"]) == 21
    assert "PR1" in data["pages"]


def test_get_page_pr1_full_text_matches_manifest():
    from gibsey_lab.fields import load_field

    data = Handlers.get_page({"field": ["holdout-21"], "id": ["PR1"]})
    field = load_field("holdout-21")
    assert data["text"] == field.manifest["PR1"].text
    assert data["sha256"] == field.manifest["PR1"].sha256


def test_get_saved_result_pr1_develop_is_recorded_pr4():
    data = Handlers.get_saved_result({"field": ["holdout-21"], "source": ["PR1"], "operator": ["DEVELOP"]})
    assert data["recorded"] is True
    assert data["selected_id"] == "PR4"
    assert data["is_abstention"] is False


def test_get_saved_result_never_preloads_for_expanded_field():
    data = Handlers.get_saved_result({"field": ["full-41"], "source": ["PR1"], "operator": ["DEVELOP"]})
    assert data["recorded"] is False


def test_get_saved_result_missing_params_is_api_error():
    with pytest.raises(ApiError):
        Handlers.get_saved_result({"field": ["holdout-21"]})


# --- proposal vs. traversal: requesting/viewing must never move the reader ---

def _write_fake_run(base_dir, run_id="fake_run", selected_id="PR4", is_abstention=False):
    run_dir = base_dir / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "input.json").write_text(json.dumps({
        "run_id": run_id, "case_id": "reader-holdout-21-pr1-develop",
        "source_id": "PR1", "active_id": None,
    }))
    (run_dir / "result.json").write_text(json.dumps({
        "is_abstention": is_abstention,
        "selected_id": None if is_abstention else selected_id,
        "selected_text": None if is_abstention else "destination text",
        "confidence": 0.5,
    }))
    return run_dir


def test_propose_alone_does_not_move_reader(tmp_path):
    run_dir = _write_fake_run(tmp_path / "runs")
    before = Handlers.get_reader_state({})
    assert before["active_page"] is None

    result = Handlers.post_propose({"run_dir": str(run_dir)})
    assert result["proposal_id"].startswith("prop_")

    after = Handlers.get_reader_state({})
    assert after == before  # proposing must not move the reader


def test_accept_alone_does_not_move_reader(tmp_path):
    run_dir = _write_fake_run(tmp_path / "runs")
    proposal_id = Handlers.post_propose({"run_dir": str(run_dir)})["proposal_id"]
    before = Handlers.get_reader_state({})

    Handlers.post_accept({"proposal_id": proposal_id})

    after = Handlers.get_reader_state({})
    assert after == before  # accepting must not move the reader either


def test_follow_moves_the_reader(tmp_path):
    run_dir = _write_fake_run(tmp_path / "runs")
    proposal_id = Handlers.post_propose({"run_dir": str(run_dir)})["proposal_id"]
    bond_id = Handlers.post_accept({"proposal_id": proposal_id})["bond_id"]

    result = Handlers.post_follow({"bond_id": bond_id})
    assert result["active_passage"] == "PR4"

    after = Handlers.get_reader_state({})
    assert after["active_passage"] == "PR4"
    assert len(after["history"]) == 1


def test_accept_and_follow_records_all_three_as_separate_events(tmp_path):
    run_dir = _write_fake_run(tmp_path / "runs")
    outcome = Handlers.post_accept_and_follow({"run_dir": str(run_dir)})
    assert outcome["proposal_id"].startswith("prop_")
    assert outcome["bond_id"].startswith("bond_")
    assert outcome["reader_state"]["active_passage"] == "PR4"

    proposals = json.loads((tmp_path / "data" / "proposals.json").read_text())
    bonds = json.loads((tmp_path / "data" / "bonds.json").read_text())
    reader_state = json.loads((tmp_path / "data" / "reader_state.json").read_text())
    assert len(proposals) == 1 and len(bonds) == 1
    assert reader_state["history"][0]["event"] == "Q_follow"


def test_cannot_propose_from_abstained_run(tmp_path):
    run_dir = _write_fake_run(tmp_path / "runs", is_abstention=True)
    with pytest.raises(ApiError):
        Handlers.post_propose({"run_dir": str(run_dir)})


# --- repeat-safe preservation ---

def test_preserve_is_repeat_safe(tmp_path):
    run_dir = _write_fake_run(tmp_path / "runs")
    outcome = Handlers.post_accept_and_follow({"run_dir": str(run_dir)})
    bond_id = outcome["bond_id"]

    entry1 = Handlers.post_preserve({"bond_id": bond_id})["entry_id"]
    entry2 = Handlers.post_preserve({"bond_id": bond_id})["entry_id"]
    assert entry1 == entry2

    index = json.loads((tmp_path / "data" / "gibsey_vault" / "index.json").read_text())
    assert len(index) == 1


# --- request-selection: a clearly labeled mock check of the live-call code path ---

def test_request_selection_wires_to_run_case_without_a_real_network_call(monkeypatch, tmp_path):
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

    saved_run_dir = list((tmp_path / "runs").iterdir())[0]
    assert saved_run_dir.name.endswith("_reader-holdout-21-PR1-develop_live")


def test_request_selection_requires_credentials(monkeypatch):
    monkeypatch.setattr(reader_server, "load_config", lambda: Config(model="jev-latest", api_key=None))
    with pytest.raises(ApiError):
        Handlers.post_request_selection({"field": "holdout-21", "source": "PR1", "operator": "ECHO"})


# --- optional review notes: never touch Jev input ---

def test_review_note_is_optional_and_separate_from_run_input(tmp_path):
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
    monkeypatch.setattr(reader_server, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(reader_server, "RUNS_DIR", tmp_path / "runs")

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
            assert data["fields"][0]["id"] == "holdout-21"

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/saved-result?field=holdout-21&source=PR1&operator=DEVELOP", timeout=5
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
