"""Reader interaction risks: outcome states, reruns, single-flight, stale responses,
GET-never-dispatches, follow-time validation, duplicate traversal, event order, offers,
atlas inspection. Everything runs against tmp_path with fakes -- no live provider call,
no real data/ or runs/ write, and never port 8765."""
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from gibsey_lab import fields as fields_module
from gibsey_lab import jev_client, runner, session_log, state
from gibsey_lab.config import Config
from gibsey_lab.fields import Field, load_field
from gibsey_lab.jev_client import JevError
from gibsey_lab.reader import outcomes
from gibsey_lab.reader import server as reader_server
from gibsey_lab.reader.server import ApiError, Handlers
from gibsey_lab.results import ChoiceResult


class FakeJev:
    """Stands in for jev_client.run_choice (the lowest real seam). Counts dispatches."""

    def __init__(self, choice="PR4", delay=0.0, error=None):
        self.choice, self.delay, self.error = choice, delay, error
        self.calls = 0
        self.block_first = None  # threading.Event: the first call waits on it
        self._lock = threading.Lock()

    def __call__(self, cfg, *, state, instructions, criteria):
        with self._lock:
            self.calls += 1
            number = self.calls
        if number == 1 and self.block_first is not None:
            assert self.block_first.wait(10)
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise JevError(self.error)
        choice = self.choice if self.choice in criteria else "NONE"
        return ChoiceResult(requested_model=cfg.model, returned_model="fake-jev", choice=choice,
                            confidence=0.41, probabilities={choice: 0.41}, live=True)


def _must_not_dispatch(*_args, **_kwargs):
    raise AssertionError("provider work was dispatched where none is allowed")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(reader_server, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(reader_server, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(reader_server, "SESSION_LOG_PATH", tmp_path / "session_log.jsonl")
    monkeypatch.setattr(reader_server, "OUTCOMES_PATH", tmp_path / "data" / "reader_outcomes.jsonl")
    monkeypatch.setattr(reader_server, "OFFER_SETS_PATH", tmp_path / "data" / "reader_offer_sets.jsonl")
    monkeypatch.setattr(reader_server, "OPTION_SETS_PATH", tmp_path / "data" / "reader_option_sets.jsonl")
    monkeypatch.setattr(reader_server, "OPTIONS_PROVIDER", _must_not_dispatch)
    monkeypatch.setattr(reader_server, "OPTIONS_REFINER", _must_not_dispatch)
    monkeypatch.setattr(reader_server, "DEMO_DIR", tmp_path / "demo")
    monkeypatch.setattr(reader_server, "load_config", lambda: Config(model="jev-latest", api_key="test-key-not-real"))
    monkeypatch.setattr(reader_server, "OFFERS_BUILDER", _must_not_dispatch)
    monkeypatch.setattr(reader_server, "OFFER_DISPATCH_FACTORY", _must_not_dispatch)
    monkeypatch.setattr(reader_server, "PROFILES_PROVIDER", lambda source, mode: [])
    monkeypatch.setattr(jev_client, "run_choice", _must_not_dispatch)
    monkeypatch.setattr(runner, "RETRY_SLEEP_SECONDS", 0.0)
    monkeypatch.setattr(reader_server, "FLIGHTS", reader_server.SingleFlight())
    reader_server._LATEST_REQUEST.clear()
    return tmp_path


@pytest.fixture
def fake_jev(monkeypatch):
    fake = FakeJev()
    monkeypatch.setattr(jev_client, "run_choice", fake)
    return fake


def _outcome_lines(tmp_path):
    return outcomes.read_outcomes(tmp_path / "data" / "reader_outcomes.jsonl")


def _events(tmp_path):
    return session_log.read_events(tmp_path / "session_log.jsonl")


def _view(page, via="dropdown", event="page_viewed"):
    Handlers.post_session_navigation({"event": event, "field": "full-41", "page_id": page, "via": via})


def _select(**overrides):
    body = {"field": "full-41", "source": "PR1", "operator": "DEVELOP", "policy": "discovery"}
    body.update(overrides)
    return Handlers.post_request_selection(body)


# --- outcome states: abstained vs no_candidates vs error are different, persisted facts ---

def test_selected_outcome_is_persisted_with_page_hash_policy_and_run_dir(isolated, fake_jev):
    record = _select(request_id="req-1")
    assert record["state"] == "selected" and record["request_id"] == "req-1"
    assert record["result"]["selected_id"] == "PR4"
    [line] = _outcome_lines(isolated)
    field = load_field("full-41")
    assert line["kind"] == "operator" and line["state"] == "selected" and line["destination"] == "PR4"
    assert line["page_sha256"] == field.manifest["PR1"].sha256
    assert line["policy"] == "discovery" and line["criteria_version"] == "v0.2"
    assert line["run_dir"] == record["run_dir"] and line["request_ids"] == ["req-1"]
    assert line["source"] == "new" and line["outcome_id"] == record["outcome_id"]


def test_abstention_says_jev_was_asked_and_how_many_candidates_it_declined(isolated, fake_jev):
    fake_jev.choice = "NONE"
    record = _select(source="PR2", operator="CONTRADICT")
    assert record["state"] == "abstained"
    assert fake_jev.calls == 1  # Jev really was asked
    assert record["candidate_count"] == 38  # 40 others minus PR1/PR3 under discovery
    assert "chose NONE" in record["message"] and "38 eligible candidates" in record["message"]
    assert "no eligible destination" not in record["message"]  # the old conflated sentence is gone
    assert _outcome_lines(isolated)[0]["state"] == "abstained"


def test_no_candidates_never_asks_jev_and_is_worded_differently(isolated, monkeypatch, fake_jev):
    real = load_field("full-41")
    tiny = Field(id="full-41", label="two adjacent pages", manifest={p: real.manifest[p] for p in ("PR1", "PR2")})
    monkeypatch.setattr(fields_module, "load_field", lambda _field_id: tiny)

    record = _select(source="PR1")
    assert record["state"] == "no_candidates" and record["candidate_count"] == 0
    assert fake_jev.calls == 0  # never asked
    assert record["run_dir"] is None and not (isolated / "runs").exists()
    assert "never asked" in record["message"] and "chose NONE" not in record["message"]
    [line] = _outcome_lines(isolated)
    assert line["state"] == "no_candidates" and line["run_dir"] is None


def test_the_three_non_selection_states_render_with_distinct_wording():
    base = {"page_id": "PR2", "policy": "discovery", "candidate_count": 38}
    messages = {
        s: outcomes.describe_operator_outcome({**base, "state": s, "error": "boom"})
        for s in ("abstained", "no_candidates", "error", "not_requested", "loading")
    }
    assert len(set(messages.values())) == 5
    assert "38" in messages["abstained"] and "never asked" in messages["no_candidates"] and "boom" in messages["error"]


def test_provider_error_is_persisted_as_an_error_outcome_with_its_run_dir(isolated, fake_jev):
    fake_jev.error = "connection reset"
    record = _select()
    assert record["state"] == "error" and record["result"] is None
    assert "connection reset" in record["error"]
    [line] = _outcome_lines(isolated)
    assert line["state"] == "error" and "connection reset" in line["error"] and line["run_dir"]
    assert line["run_dir"].endswith("_error")


def test_server_side_exception_is_persisted_as_an_error_outcome(isolated, monkeypatch):
    def explode(*_a, **_k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(reader_server, "run_case", explode)
    with pytest.raises(ApiError) as excinfo:
        _select(request_id="req-x")
    assert excinfo.value.status == 500
    assert excinfo.value.payload["state"] == "error" and excinfo.value.payload["request_id"] == "req-x"
    [line] = _outcome_lines(isolated)
    assert line["state"] == "error" and "RuntimeError: disk full" in line["error"]


def test_missing_credentials_is_a_persisted_error_and_never_dispatches(isolated, monkeypatch):
    monkeypatch.setattr(reader_server, "load_config", lambda: Config(model="jev-latest", api_key=None))
    with pytest.raises(ApiError) as excinfo:
        _select()
    assert excinfo.value.status == 503
    assert _outcome_lines(isolated)[0]["state"] == "error"


# --- reruns append; earlier outcomes stay retrievable ---

def test_rerun_appends_a_new_outcome_and_a_new_run_dir_and_keeps_the_earlier_ones(isolated, fake_jev):
    fake_jev.choice = "NONE"
    first = _select(source="PR2", operator="CONTRADICT", request_id="r1")
    second = _select(source="PR2", operator="CONTRADICT", request_id="r2")  # immediate, same-second rerun
    third = _select(source="PR2", operator="CONTRADICT", request_id="r3")
    assert fake_jev.calls == 3  # sequential reruns are real, separate requests
    run_dirs = {first["run_dir"], second["run_dir"], third["run_dir"]}
    assert len(run_dirs) == 3  # the same-second record_run collision is guarded

    listing = Handlers.get_outcomes({"field": ["full-41"], "page": ["PR2"], "operator": ["CONTRADICT"], "policy": ["discovery"]})
    assert listing["count"] == 3
    assert [o["state"] for o in listing["outcomes"]] == ["abstained"] * 3
    assert {o["outcome_id"] for o in listing["outcomes"]} == {first["outcome_id"], second["outcome_id"], third["outcome_id"]}
    assert listing["outcomes"][0]["outcome_id"] == third["outcome_id"]  # newest first
    assert len(_outcome_lines(isolated)) == 3  # appended, never replaced


def test_one_operators_abstention_does_not_touch_another_operators_outcomes(isolated, fake_jev):
    _select(source="PR2", operator="DEVELOP")
    fake_jev.choice = "NONE"
    _select(source="PR2", operator="CONTRADICT")
    develop = Handlers.get_outcomes({"page": ["PR2"], "operator": ["DEVELOP"], "policy": ["discovery"]})
    contradict = Handlers.get_outcomes({"page": ["PR2"], "operator": ["CONTRADICT"], "policy": ["discovery"]})
    assert [o["state"] for o in develop["outcomes"]] == ["selected"]
    assert [o["state"] for o in contradict["outcomes"]] == ["abstained"]


def _write_historical_run(runs_dir, run_id, *, source="PR2", operator="CONTRADICT", abstained=True, policy="discovery"):
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    field = load_field("full-41")
    order = field.eligible_candidate_ids(source, policy) + ["NONE"]
    (run_dir / "input.json").write_text(json.dumps({
        "run_id": run_id, "case_id": f"reader-full-41-{source}-{operator.lower()}-v0.2-{policy}",
        "source_id": source, "active_id": None, "criterion": "c", "option_order": order,
        "reader_state": {"app": "reader", "field": "full-41", "operator": operator, "policy": policy, "criteria_version": "v0.2"},
        "corpus_hashes": {pid: p.sha256 for pid, p in field.manifest.items()},
    }))
    (run_dir / "response.json").write_text(json.dumps({"live": True, "returned_model": "jev-1.13.0", "error": None}))
    (run_dir / "result.json").write_text(json.dumps({
        "is_abstention": abstained, "selected_id": None if abstained else "PR5",
        "selected_text": None if abstained else "text", "confidence": 0.36, "probabilities": {},
    }))
    return run_dir


def test_outcomes_backfill_historical_abstentions_recorded_before_the_outcome_log_existed(isolated):
    runs = isolated / "runs"
    for stamp in ("20260920T045250Z", "20260920T165521Z", "20260920T165734Z"):
        _write_historical_run(runs, f"{stamp}_reader-full-41-PR2-contradict-v0.2-discovery_live")
    _write_historical_run(runs, "20260920T045249Z_reader-full-41-PR2-echo-v0.2-discovery_live", operator="ECHO")

    listing = Handlers.get_outcomes({"page": ["PR2"], "operator": ["CONTRADICT"], "policy": ["discovery"]})
    assert listing["count"] == 3
    assert all(o["state"] == "abstained" and o["source"] == "recorded" for o in listing["outcomes"])
    assert all("38 eligible candidates" in o["message"] for o in listing["outcomes"])
    assert not (isolated / "data" / "reader_outcomes.jsonl").exists()  # a computed view: the GET wrote nothing


# --- duplicate / stale protection ---

def test_two_concurrent_identical_requests_cause_one_dispatch_and_both_get_the_result(isolated, fake_jev):
    fake_jev.delay = 0.4
    results, errors = {}, []

    def ask(request_id):
        try:
            results[request_id] = _select(request_id=request_id)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=ask, args=(rid,)) for rid in ("dup-a", "dup-b")]
    threads[0].start()
    time.sleep(0.1)  # the second click lands while the first is in flight
    threads[1].start()
    for t in threads:
        t.join(10)

    assert not errors
    assert fake_jev.calls == 1  # ONE provider dispatch
    assert len(list((isolated / "runs").iterdir())) == 1
    assert results["dup-a"]["request_id"] == "dup-a" and results["dup-b"]["request_id"] == "dup-b"  # each echoes its own id
    assert results["dup-a"]["run_dir"] == results["dup-b"]["run_dir"]
    assert {results["dup-a"]["joined"], results["dup-b"]["joined"]} == {False, True}
    [line] = _outcome_lines(isolated)
    assert sorted(line["request_ids"]) == ["dup-a", "dup-b"]

    _select(request_id="later")  # after the flight closed, a new request is a genuine rerun
    assert fake_jev.calls == 2


def test_a_superseded_request_is_still_persisted_but_flagged_not_applicable(isolated, fake_jev):
    fake_jev.block_first = threading.Event()
    results = {}
    slow = threading.Thread(target=lambda: results.update(old=_select(request_id="old", policy="discovery")))
    slow.start()
    for _ in range(200):
        if fake_jev.calls >= 1:
            break
        time.sleep(0.01)

    results["new"] = _select(request_id="new", policy="include-adjacent")  # newer request, same page+operator
    fake_jev.block_first.set()
    slow.join(10)

    assert results["new"]["applicable"] is True
    assert results["old"]["applicable"] is False and "superseded" in results["old"]["not_applicable_reason"]
    by_request = {line["request_id"]: line for line in _outcome_lines(isolated)}
    assert by_request["old"]["applicable"] is False  # persisted all the same
    assert by_request["old"]["state"] == "selected" and by_request["old"]["run_dir"]


def test_a_response_for_a_page_the_reader_has_left_is_flagged_not_applicable(isolated, fake_jev):
    Handlers.post_session_navigation({"event": "page_viewed", "field": "full-41", "page_id": "LF3"})
    record = _select(source="PR1")
    assert record["applicable"] is False and "LF3" in record["not_applicable_reason"]
    assert _outcome_lines(isolated)[0]["applicable"] is False


def test_get_endpoints_and_page_loads_never_dispatch_provider_work(isolated, monkeypatch):
    monkeypatch.setattr(reader_server, "run_case", _must_not_dispatch)
    monkeypatch.setattr(reader_server, "CORE_DIR", isolated / "core")  # never the real data/core
    session_id = Handlers.post_core_session({"page": "PR2"})["session_id"]
    queries = {
        "/api/core/session": {"session_id": [session_id]},
        "/api/core/status": {"session_id": [session_id], "request_id": ["none"]},
        "/api/core/journey": {"session_id": [session_id]},
        "/api/fields": {},
        "/api/field-status": {"field": ["full-41"]},
        "/api/pages": {"field": ["full-41"]},
        "/api/page": {"field": ["full-41"], "id": ["PR2"]},
        "/api/saved-result": {"field": ["full-41"], "source": ["PR2"], "operator": ["CONTRADICT"]},
        "/api/reader-state": {},
        "/api/outcomes": {"page": ["PR2"], "operator": ["CONTRADICT"]},
        "/api/offers/latest": {"page": ["PR2"]},
        "/api/atlas/profiles": {"source": ["PR2"]},
        "/api/operator-options": {"page": ["PR2"], "operator": ["CONTRADICT"]},
        "/api/build": {},
    }
    assert set(queries) == set(reader_server.GET_ROUTES)  # every GET route is covered
    for path, query in queries.items():
        reader_server.GET_ROUTES[path](query)  # any dispatch would raise via the autouse fakes
    assert not (isolated / "runs").exists()
    assert _outcome_lines(isolated) == []


# --- proposal / acceptance / traversal ---

def _recorded_run(isolated, fake_jev, **overrides):
    record = _select(**overrides)
    assert record["state"] == "selected"
    return record


def test_requesting_and_proposing_leave_the_reader_position_unchanged(isolated, fake_jev):
    before = state.reader_state(data_dir=isolated / "data")
    record = _recorded_run(isolated, fake_jev)
    Handlers.post_propose({"run_dir": record["run_dir"]})
    Handlers.post_session_navigation({"event": "offer_previewed", "field": "full-41", "page_id": "PR1", "destination_id": "PR4"})
    assert state.reader_state(data_dir=isolated / "data") == before


def test_follow_records_proposal_acceptance_and_traversal_separately_and_in_order(isolated, fake_jev):
    record = _recorded_run(isolated, fake_jev)
    outcome = Handlers.post_accept_and_follow({
        "run_dir": record["run_dir"], "field": "full-41", "source": "PR1", "operator": "DEVELOP",
        "from_page": "PR1", "follow_token": "tok-1",
    })
    assert outcome["reader_state"]["active_passage"] == "PR4" and outcome["duplicate"] is False

    data = isolated / "data"
    proposals = json.loads((data / "proposals.json").read_text())
    bonds = json.loads((data / "bonds.json").read_text())
    history = json.loads((data / "reader_state.json").read_text())["history"]
    assert len(proposals) == 1 and len(bonds) == 1 and len(history) == 1  # three separate records
    field = load_field("full-41")
    [bond] = bonds.values()
    assert bond["source_sha256"] == field.manifest["PR1"].sha256  # both endpoint versions on the bond
    assert bond["destination_sha256"] == field.manifest["PR4"].sha256
    assert bond["policy"] == "discovery" and history[0]["from_page"] == "PR1"

    names = [e["event"] for e in _events(isolated)]
    tail = names[names.index("operator_proposed"):]
    assert tail == ["operator_proposed", "offer_accepted", "accept_and_follow", "q_traversal", "page_viewed"]
    viewed = _events(isolated)[-1]
    assert viewed["via"] == "traversal" and viewed["page_id"] == "PR4"
    assert viewed["page_sha256"] == field.manifest["PR4"].sha256


def test_a_duplicate_follow_token_is_one_traversal_and_one_history_entry(isolated, fake_jev):
    record = _recorded_run(isolated, fake_jev)
    body = {"run_dir": record["run_dir"], "field": "full-41", "source": "PR1", "from_page": "PR1", "follow_token": "same"}
    first = Handlers.post_accept_and_follow(dict(body))
    second = Handlers.post_accept_and_follow(dict(body))  # the double click
    assert first["duplicate"] is False and second["duplicate"] is True
    assert second["bond_id"] == first["bond_id"] and second["destination"] == "PR4"
    assert len(second["reader_state"]["history"]) == 1
    assert [e["event"] for e in _events(isolated)].count("q_traversal") == 1


def _tamper(run_dir, mutate_input=None, mutate_result=None):
    from pathlib import Path

    run_dir = Path(run_dir)
    if mutate_input:
        record = json.loads((run_dir / "input.json").read_text())
        mutate_input(record)
        (run_dir / "input.json").write_text(json.dumps(record))
    if mutate_result:
        record = json.loads((run_dir / "result.json").read_text())
        mutate_result(record)
        (run_dir / "result.json").write_text(json.dumps(record))


def _assert_rejected_and_nothing_moved(isolated, body, match):
    with pytest.raises(ApiError, match=match) as excinfo:
        Handlers.post_accept_and_follow(body)
    assert excinfo.value.status == 409
    data = isolated / "data"
    assert not (data / "proposals.json").exists() and not (data / "bonds.json").exists()
    assert state.reader_state(data_dir=data)["active_page"] is None
    assert "q_traversal" not in [e["event"] for e in _events(isolated)]


def test_follow_is_rejected_when_the_destination_page_changed_since_the_proposal(isolated, fake_jev):
    record = _recorded_run(isolated, fake_jev)
    _tamper(record["run_dir"], mutate_input=lambda r: r["corpus_hashes"].update(PR4="0" * 64))
    _assert_rejected_and_nothing_moved(
        isolated, {"run_dir": record["run_dir"], "from_page": "PR1", "follow_token": "t"}, "destination page 'PR4' has changed")


def test_follow_is_rejected_when_the_source_page_changed_since_the_proposal(isolated, fake_jev):
    record = _recorded_run(isolated, fake_jev)
    _tamper(record["run_dir"], mutate_input=lambda r: r["corpus_hashes"].update(PR1="0" * 64))
    _assert_rejected_and_nothing_moved(
        isolated, {"run_dir": record["run_dir"], "from_page": "PR1", "follow_token": "t"}, "source page 'PR1' has changed")


def test_follow_is_rejected_when_the_destination_is_ineligible_under_the_recorded_policy(isolated, fake_jev):
    record = _recorded_run(isolated, fake_jev)  # recorded under discovery, source PR1
    _tamper(record["run_dir"], mutate_result=lambda r: r.update(selected_id="PR2"))  # PR2 is PR1's authored neighbor
    _assert_rejected_and_nothing_moved(
        isolated, {"run_dir": record["run_dir"], "from_page": "PR1", "follow_token": "t"}, "not eligible")


def test_follow_is_rejected_from_the_wrong_page(isolated, fake_jev):
    record = _recorded_run(isolated, fake_jev)
    _assert_rejected_and_nothing_moved(
        isolated, {"run_dir": record["run_dir"], "from_page": "LF3", "follow_token": "t"}, "starts from 'PR1'")
    _assert_rejected_and_nothing_moved(
        isolated, {"run_dir": record["run_dir"], "from_page": "PR1", "source": "LF3", "follow_token": "t"}, "starts from 'PR1'")


def test_follow_is_rejected_when_the_session_log_says_the_reader_is_elsewhere(isolated, fake_jev):
    record = _recorded_run(isolated, fake_jev)
    Handlers.post_session_navigation({"event": "page_viewed", "field": "full-41", "page_id": "LF3"})
    _assert_rejected_and_nothing_moved(
        isolated, {"run_dir": record["run_dir"], "from_page": "PR1", "follow_token": "t"}, "last recorded on 'LF3'")


def test_follow_is_rejected_for_an_unknown_destination(isolated, fake_jev):
    record = _recorded_run(isolated, fake_jev)
    _tamper(record["run_dir"], mutate_result=lambda r: r.update(selected_id="ZZ9"))
    _assert_rejected_and_nothing_moved(
        isolated, {"run_dir": record["run_dir"], "from_page": "PR1", "follow_token": "t"}, "not a page in field")


def test_abstained_and_error_runs_can_never_be_followed(isolated, fake_jev):
    fake_jev.choice = "NONE"
    record = _select()
    _assert_rejected_and_nothing_moved(
        isolated, {"run_dir": record["run_dir"], "from_page": "PR1", "follow_token": "t"}, "abstained")


def test_a_run_dir_outside_the_recorded_runs_directory_is_refused(isolated, tmp_path):
    outside = tmp_path / "elsewhere" / "run"
    outside.mkdir(parents=True)
    with pytest.raises(ApiError, match="not inside"):
        Handlers.post_propose({"run_dir": str(outside)})


# --- session log: back keeps encounters; event fields ---

def test_back_adds_an_encounter_and_removes_nothing(isolated):
    for page, event, via in (("P1", "page_viewed", "dropdown"), ("P2", "page_viewed", "next"), ("P1", "back", "back")):
        Handlers.post_session_navigation({"event": event, "field": "full-41", "page_id": page, "via": via, "policy": "discovery"})
    events = _events(isolated)
    assert [(e["event"], e["page_id"]) for e in events] == [("page_viewed", "P1"), ("page_viewed", "P2"), ("back", "P1")]
    assert [e["seq"] for e in events] == [0, 1, 2]
    field = load_field("full-41")
    assert events[1]["page_sha256"] == field.manifest["P2"].sha256 and events[1]["policy"] == "discovery"


# --- offers ---

def _offer_result(state_id, *, page="PR2", offers=None, assessed=None, not_assessed=30, **extra):
    field = load_field("full-41")
    return {
        "schema": "offer-result/1", "offer_set_id": f"offers_test_{state_id}_{page}", "at": "2026-09-20T18:00:00+00:00",
        "field": "full-41", "page_id": page, "page_sha256": field.manifest[page].sha256, "policy": "discovery",
        "mode": "mock", "state": state_id,
        "memory_packet": {"encounters": [{"seq": 0, "page_id": "PR1", "text": "secret page text"}],
                          "omitted_earlier_encounters": 2, "intention": None, "source": "session_log"},
        "memory_sha256": "m" * 64, "base_counts": {"complete": 12, "unassessed": 28},
        "shortlist": [], "assessed_ids": assessed if assessed is not None else [], "not_assessed_count": not_assessed,
        "offers": offers or [], "rejected": [], "versions": {"requested_model": "mock"}, "usage": {"requests_dispatched": 1},
        "errors": [], **extra,
    }


def _offer(dest, labels=("DEVELOP",), sha=None):
    field = load_field("full-41")
    return {"rank": 1, "destination_id": dest, "destination_sha256": sha or field.manifest[dest].sha256,
            "relation_labels": list(labels), "base": {"dimensions": {"development": {"score": 2.0}}},
            "contextual": {"answers": {"works_after_history": {"score": 0.8, "confidence": 0.7}}},
            "from_cache": False, "rank_reasons": ["r"]}


def _ask_offers(body):
    """Arrive on the page (the server requires the log to say the reader is there), then ask."""
    Handlers.post_session_navigation({"event": "page_viewed", "field": "full-41", "page_id": body["page"], "via": "dropdown"})
    return Handlers.post_offers(body)


def _install_builder(monkeypatch, result=None, *, error=None, calls=None):
    def builder(field, page_id, events, **kwargs):
        if calls is not None:
            calls.append({"field": field, "page_id": page_id, "events": events, **kwargs})
        if error:
            raise error
        if isinstance(result, dict) and result.get("state"):
            # like the real builder: the hand records the hash of the memory it was computed for
            from gibsey_lab.memory.packet import build_memory_packet, memory_sha256

            packet = build_memory_packet(field, page_id, events, candidate_policy=kwargs["policy"], intention=kwargs.get("intention"))
            return {**result, "memory_sha256": memory_sha256(packet),
                    "memory_packet": {**result["memory_packet"], "intention": packet["intention"]}}
        return result

    monkeypatch.setattr(reader_server, "OFFERS_BUILDER", builder)
    monkeypatch.setattr(reader_server, "OFFER_DISPATCH_FACTORY", lambda: ("fake-dispatch", "mock", "mock-model"))


def test_offers_endpoint_passes_session_events_and_dispatch_to_the_builder_and_persists_the_hand(isolated, monkeypatch):
    calls = []
    Handlers.post_session_navigation({"event": "page_viewed", "field": "full-41", "page_id": "PR2"})
    _install_builder(monkeypatch, _offer_result("offers", offers=[_offer("PR5")], assessed=list("abcdefgh"), not_assessed=30), calls=calls)
    before = state.reader_state(data_dir=isolated / "data")

    view = Handlers.post_offers({"field": "full-41", "page": "PR2", "policy": "discovery", "request_id": "of-1", "intention": " find echoes "})
    [call] = calls
    assert call["field"].id == "full-41" and call["page_id"] == "PR2" and call["policy"] == "discovery"
    assert call["dispatch"] == "fake-dispatch" and call["mode"] == "mock" and call["requested_model"] == "mock-model"
    assert call["intention"] == "find echoes"
    assert [e["seq"] for e in call["events"]] == [0] and call["events"][0]["page_id"] == "PR2"

    assert view["state"] == "offers" and view["request_id"] == "of-1" and view["applicable"] is True
    assert view["message"] == "1 route qualified of 8 assessed (30 eligible pages were not contextually assessed)."
    assert view["offers"][0]["relation_labels"] == ["DEVELOP"]
    assert view["reader_display"]["PR5"]["text"] == load_field("full-41").manifest["PR5"].text  # exact authored text
    assert "text" not in view["memory_packet"]["encounters"][0]  # history texts are not echoed to the browser
    assert view["memory_summary"]["encounters_supplied"] == 1 and view["memory_summary"]["encounters_omitted"] == 2
    assert state.reader_state(data_dir=isolated / "data") == before  # an offered hand never moves the reader

    [line] = _outcome_lines(isolated)
    assert line["kind"] == "offers" and line["state"] == "offers" and line["offer_set_id"] == view["offer_set_id"]
    assert line["destinations"] == ["PR5"]


@pytest.mark.parametrize("state_id,needle", [
    ("no_qualified", "No route qualified"),
    ("no_candidates", "No eligible candidate pages"),
    ("atlas_incomplete", "atlas is not complete"),
    ("error", "offer request failed"),
])
def test_each_empty_offer_state_is_persisted_with_its_own_wording(isolated, monkeypatch, state_id, needle):
    extra = {"errors": ["every contextual request failed"]} if state_id == "error" else {}
    _install_builder(monkeypatch, _offer_result(state_id, assessed=["a", "b"], **extra))
    view = _ask_offers({"page": "PR2"})
    assert view["state"] == state_id and needle in view["message"] and view["offers"] == []
    assert _outcome_lines(isolated)[0]["state"] == state_id
    wordings = {outcomes.describe_offer_outcome(_offer_result(s)) for s in
                ("offers", "no_qualified", "no_candidates", "atlas_incomplete", "error")}
    assert len(wordings) == 5


def test_a_builder_exception_is_a_persisted_error_outcome(isolated, monkeypatch):
    _install_builder(monkeypatch, error=RuntimeError("atlas store unreadable"))
    with pytest.raises(ApiError) as excinfo:
        _ask_offers({"page": "PR2", "request_id": "of-err"})
    assert excinfo.value.status == 500 and excinfo.value.payload["state"] == "error"
    assert excinfo.value.payload["request_id"] == "of-err"
    assert "atlas store unreadable" in _outcome_lines(isolated)[0]["error"]
    latest = Handlers.get_offers_latest({"page": ["PR2"]})
    assert latest["found"] is True and latest["state"] == "error"


def test_unwired_live_dispatch_is_a_clear_503_and_a_persisted_error(isolated, monkeypatch):
    monkeypatch.setattr(reader_server, "OFFER_DISPATCH_FACTORY", reader_server._default_offer_dispatch_factory)
    with pytest.raises(ApiError, match="lead-wired") as excinfo:
        _ask_offers({"page": "PR2"})
    assert excinfo.value.status == 503
    assert _outcome_lines(isolated)[0]["state"] == "error"


def test_latest_offers_is_served_from_the_store_without_dispatching(isolated, monkeypatch):
    assert Handlers.get_offers_latest({"page": ["PR2"]}) == {
        "found": False, "state": "not_requested", "field": "full-41", "page_id": "PR2", "policy": "discovery", "earlier_count": 0}
    _install_builder(monkeypatch, _offer_result("offers", offers=[_offer("PR5")], assessed=["PR5"]))
    posted = _ask_offers({"page": "PR2"})
    monkeypatch.setattr(reader_server, "OFFERS_BUILDER", _must_not_dispatch)
    monkeypatch.setattr(reader_server, "OFFER_DISPATCH_FACTORY", _must_not_dispatch)
    latest = Handlers.get_offers_latest({"page": ["PR2"], "policy": ["discovery"]})
    assert latest["found"] is True and latest["from_store"] is True
    assert latest["offer_set_id"] == posted["offer_set_id"] and latest["offers"][0]["destination_id"] == "PR5"
    assert Handlers.get_offers_latest({"page": ["PR2"], "policy": ["include-adjacent"]})["found"] is False


def test_concurrent_identical_offer_requests_build_once(isolated, monkeypatch):
    calls = []

    def slow_builder(field, page_id, events, **kwargs):
        calls.append(page_id)
        time.sleep(0.4)
        return _offer_result("no_qualified", assessed=["a"])

    monkeypatch.setattr(reader_server, "OFFERS_BUILDER", slow_builder)
    monkeypatch.setattr(reader_server, "OFFER_DISPATCH_FACTORY", lambda: (None, "mock", "m"))
    results = {}
    _view("PR2")
    threads = [threading.Thread(target=lambda rid=rid: results.update({rid: Handlers.post_offers({"page": "PR2", "request_id": rid})}))
               for rid in ("o1", "o2")]
    threads[0].start()
    time.sleep(0.1)
    threads[1].start()
    for t in threads:
        t.join(10)
    assert calls == ["PR2"] and results["o1"]["request_id"] == "o1" and results["o2"]["request_id"] == "o2"
    assert len(_outcome_lines(isolated)) == 1


def _posted_hand(monkeypatch, offers, page="PR2"):
    _install_builder(monkeypatch, _offer_result("offers", page=page, offers=offers, assessed=[o["destination_id"] for o in offers]))
    return _ask_offers({"page": page})


def test_follow_offer_validates_then_records_propose_accept_follow_separately(isolated, monkeypatch):
    Handlers.post_session_navigation({"event": "page_viewed", "field": "full-41", "page_id": "PR2", "via": "dropdown"})
    hand = _posted_hand(monkeypatch, [_offer("PR5", labels=("development",)), _offer("LF3", labels=("echo", "bridge_relation"))])
    body = {"offer_set_id": hand["offer_set_id"], "destination_id": "PR5", "from_page": "PR2", "follow_token": "ft-1"}
    outcome = Handlers.post_follow_offer(dict(body))
    assert outcome["reader_state"]["active_passage"] == "PR5" and outcome["duplicate"] is False

    data = isolated / "data"
    field = load_field("full-41")
    [proposal] = json.loads((data / "proposals.json").read_text()).values()
    [bond] = json.loads((data / "bonds.json").read_text()).values()
    assert proposal["kind"] == "offer" and proposal["status"] == "accepted"
    assert bond["offer_set_id"] == hand["offer_set_id"]
    assert bond["source_sha256"] == field.manifest["PR2"].sha256 and bond["destination_sha256"] == field.manifest["PR5"].sha256
    history = json.loads((data / "reader_state.json").read_text())["history"]
    assert len(history) == 1 and history[0]["from_page"] == "PR2"

    events = _events(isolated)
    names = [e["event"] for e in events]
    assert names[names.index("offer_proposed"):] == ["offer_proposed", "offer_accepted", "accept_and_follow", "q_traversal", "page_viewed"]
    traversal = next(e for e in events if e["event"] == "q_traversal")
    # An offered route was never an operator request: operator is null on every follow event,
    # and the labels + offer set travel as their own fields.
    for name in ("offer_proposed", "accept_and_follow", "q_traversal", "page_viewed"):
        event = next(e for e in events if e["event"] == name and e.get("offer_set_id") == hand["offer_set_id"])
        assert event["operator"] is None and event["relation_labels"] == ["development"], name
    assert traversal["proposal_kind"] == "offer"
    assert [e["seq"] for e in events] == list(range(len(events)))

    again = Handlers.post_follow_offer(dict(body))  # double click
    assert again["duplicate"] is True and len(again["reader_state"]["history"]) == 1
    assert [e["event"] for e in _events(isolated)].count("q_traversal") == 1


def test_the_next_memory_packet_calls_an_offer_follow_an_offered_route_not_an_operator_offer(isolated, monkeypatch):
    from gibsey_lab.memory.packet import build_memory_packet, model_visible_state

    Handlers.post_session_navigation({"event": "page_viewed", "field": "full-41", "page_id": "PR2", "via": "dropdown"})
    hand = _posted_hand(monkeypatch, [_offer("PR5", labels=("contradiction",))])
    Handlers.post_follow_offer({"offer_set_id": hand["offer_set_id"], "destination_id": "PR5", "from_page": "PR2", "follow_token": "x"})
    packet = build_memory_packet(load_field("full-41"), "PR5", session_log.read_events_with_seq(isolated / "session_log.jsonl"),
                                 candidate_policy="discovery")
    assert packet["current"]["arrived_via"] in ("offer", "traversal") and packet["current"]["operator"] is None
    assert model_visible_state(packet)["current_page_arrived_by"] == "followed an offered route"


def test_an_operator_button_follow_keeps_its_operator(isolated, fake_jev):
    record = _select()
    Handlers.post_accept_and_follow({"run_dir": record["run_dir"], "source": "PR1", "from_page": "PR1", "follow_token": "k"})
    events = _events(isolated)
    assert next(e for e in events if e["event"] == "q_traversal")["operator"] == "DEVELOP"
    assert events[-1]["event"] == "page_viewed" and events[-1]["operator"] == "DEVELOP"


# --- a hand belongs to the reading history it was computed for ---

def test_ask_then_preview_then_follow_succeeds_because_viewing_a_hand_is_not_an_encounter(isolated, monkeypatch):
    _view("PR1")
    _view("PR2", via="next")
    hand = _posted_hand(monkeypatch, [_offer("PR5")])
    assert hand["memory_current"] is True
    Handlers.post_session_navigation({"event": "offer_previewed", "field": "full-41", "page_id": "PR2",
                                      "destination_id": "PR5", "offer_set_id": hand["offer_set_id"], "via": "offer_card"})
    _view("PR2", via="reload")  # a refresh of the same page is not new history either
    latest = Handlers.get_offers_latest({"page": ["PR2"]})
    assert latest["memory_current"] is True and latest["current_memory_sha256"] == latest["memory_sha256"]
    outcome = Handlers.post_follow_offer({"offer_set_id": hand["offer_set_id"], "destination_id": "PR5",
                                          "from_page": "PR2", "follow_token": "ok"})
    assert outcome["reader_state"]["active_passage"] == "PR5"


def test_an_old_hand_is_marked_not_current_and_cannot_be_followed_after_new_history(isolated, monkeypatch):
    _view("PR1")
    _view("PR2", via="next")
    hand = _posted_hand(monkeypatch, [_offer("PR5")])
    _view("LF3")                      # navigate away ...
    _view("PR2", event="back", via="back")  # ... and come back with a different history

    monkeypatch.setattr(reader_server, "OFFERS_BUILDER", _must_not_dispatch)
    monkeypatch.setattr(reader_server, "OFFER_DISPATCH_FACTORY", _must_not_dispatch)
    latest = Handlers.get_offers_latest({"page": ["PR2"]})  # read-only: never dispatches
    assert latest["found"] is True and latest["memory_current"] is False
    assert latest["current_memory_sha256"] and latest["current_memory_sha256"] != latest["memory_sha256"]
    assert latest["memory_note"].startswith("Computed for an earlier reading history")

    with pytest.raises(ApiError, match="earlier reading history") as excinfo:
        Handlers.post_follow_offer({"offer_set_id": hand["offer_set_id"], "destination_id": "PR5",
                                    "from_page": "PR2", "follow_token": "stale-hand"})
    assert excinfo.value.status == 409 and excinfo.value.payload["memory_current"] is False
    assert not (isolated / "data" / "proposals.json").exists()  # nothing proposed, accepted or moved
    assert state.reader_state(data_dir=isolated / "data")["active_page"] is None
    assert "q_traversal" not in [e["event"] for e in _events(isolated)]
    rejected = [o for o in _outcome_lines(isolated) if o.get("event") == "follow_rejected"]
    assert len(rejected) == 1 and rejected[0]["state"] == "error" and rejected[0]["offer_set_id"] == hand["offer_set_id"]


def test_a_hand_whose_current_memory_cannot_be_recomputed_is_not_treated_as_current(isolated, monkeypatch):
    _view("PR2")
    hand = _posted_hand(monkeypatch, [_offer("PR5")])

    def broken(*_a, **_k):
        raise RuntimeError("memory package unavailable")

    monkeypatch.setattr(reader_server, "MEMORY_HASHER", broken)
    assert Handlers.get_offers_latest({"page": ["PR2"]})["memory_current"] is False
    with pytest.raises(ApiError) as excinfo:
        Handlers.post_follow_offer({"offer_set_id": hand["offer_set_id"], "destination_id": "PR5", "from_page": "PR2", "follow_token": "t"})
    assert excinfo.value.status == 409


def test_pages_without_a_complete_base_profile_are_named_in_the_headline_not_folded_into_not_assessed():
    partial = _offer_result("offers", offers=[_offer("PR5")], assessed=["a", "b"], not_assessed=3)
    partial["base_counts"] = {"complete": 5, "ineligible_policy": 2, "ineligible_incomplete": 33}
    message = outcomes.describe_offer_outcome(partial)
    assert "33 pages had no complete base profile and could not be considered" in message
    assert "3 eligible pages were not contextually assessed" in message
    full = _offer_result("offers", offers=[_offer("PR5")], assessed=["a", "b"], not_assessed=3)
    full["base_counts"] = {"ineligible_incomplete": 0}
    assert "base profile" not in outcomes.describe_offer_outcome(full)
    partial["state"], partial["offers"] = "no_qualified", []
    assert "33 pages had no complete base profile" in outcomes.describe_offer_outcome(partial)


def test_an_offer_with_several_relation_labels_is_never_collapsed_into_one_operator(isolated, monkeypatch):
    hand = _posted_hand(monkeypatch, [_offer("LF3", labels=("echo", "bridge_relation"))])
    Handlers.post_follow_offer({"offer_set_id": hand["offer_set_id"], "destination_id": "LF3", "from_page": "PR2", "follow_token": "x"})
    traversal = next(e for e in _events(isolated) if e["event"] == "q_traversal")
    assert traversal["operator"] is None and traversal["relation_labels"] == ["echo", "bridge_relation"]


@pytest.mark.parametrize("offers,body,match", [
    ([("PR5", None)], {"destination_id": "LF9"}, "not one of the routes offered"),         # never offered
    ([("PR5", "0" * 64)], {"destination_id": "PR5"}, "destination page 'PR5' has changed"),   # hash changed
    ([("PR3", None)], {"destination_id": "PR3"}, "not eligible"),                          # neighbor under discovery
    ([("PR5", None)], {"destination_id": "PR5", "from_page": "PR4"}, "starts from 'PR2'"),   # wrong page
    ([("ZZ9", "0" * 64)], {"destination_id": "ZZ9"}, "not a page in field"),                 # unknown destination
])
def test_follow_offer_rejections_are_409_and_move_nothing(isolated, monkeypatch, offers, body, match):
    built = [_offer(dest, sha=sha) if dest != "ZZ9" else
             {"rank": 1, "destination_id": dest, "destination_sha256": sha, "relation_labels": []} for dest, sha in offers]
    hand = _posted_hand(monkeypatch, built)
    request = {"offer_set_id": hand["offer_set_id"], "from_page": "PR2", "follow_token": "t", **body}
    with pytest.raises(ApiError, match=match) as excinfo:
        Handlers.post_follow_offer(request)
    assert excinfo.value.status == 409
    assert not (isolated / "data" / "proposals.json").exists()
    assert state.reader_state(data_dir=isolated / "data")["active_page"] is None


def test_an_empty_hand_cannot_be_followed(isolated, monkeypatch):
    _install_builder(monkeypatch, _offer_result("no_qualified", assessed=["a"]))
    hand = _ask_offers({"page": "PR2"})
    with pytest.raises(ApiError, match="nothing to follow"):
        Handlers.post_follow_offer({"offer_set_id": hand["offer_set_id"], "destination_id": "PR5", "from_page": "PR2", "follow_token": "t"})


# --- atlas inspection + demo ---

def test_atlas_profiles_show_unassessed_as_missing_never_zero(isolated, monkeypatch):
    dims = {d: {"score": 0.0 if d == "echo" else 2.0, "confidence": 0.9} for d in reader_server.ATLAS_DIMENSIONS}
    rows = [
        {"destination_id": "PR1", "status": "complete", "is_authored_neighbor": True, "neighbor_relation": "previous", "dimensions": dims},
        {"destination_id": "PR3", "status": "unassessed", "is_authored_neighbor": True, "dimensions": None},
        {"destination_id": "LF1", "status": "failed", "is_authored_neighbor": False, "dimensions": None, "last_errors": ["timeout"]},
        {"destination_id": "LF2", "status": "stale", "is_authored_neighbor": False, "dimensions": None},
    ]
    seen = []
    monkeypatch.setattr(reader_server, "PROFILES_PROVIDER", lambda source, mode: seen.append((source, mode)) or rows)

    data = Handlers.get_atlas_profiles({"source": ["PR2"], "mode": ["mock"]})
    assert seen == [("PR2", "mock")] and data["mode"] == "mock" and "MOCK" in data["label"]
    assert data["counts"] == {"complete": 1, "failed": 1, "stale": 1, "unassessed": 1}
    by_dest = {r["destination_id"]: r for r in data["rows"]}
    assert by_dest["PR1"]["scores"]["echo"] == 0.0  # a real low score is a value
    assert all(v is None for v in by_dest["PR3"]["scores"].values())  # unassessed: no score, never 0
    assert all(v is None for v in by_dest["LF1"]["scores"].values())
    assert "LIVE" in Handlers.get_atlas_profiles({"source": ["PR2"]})["label"]
    with pytest.raises(ApiError):
        Handlers.get_atlas_profiles({"source": ["PR2"], "mode": ["pretend"]})


def _serve():
    httpd = reader_server.ThreadingHTTPServer(("127.0.0.1", 0), reader_server.ReaderRequestHandler)  # ephemeral port
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def test_http_demo_page_static_page_and_error_payloads(isolated, monkeypatch):
    httpd, base = _serve()
    try:
        with urllib.request.urlopen(f"{base}/demo/pr2", timeout=5) as resp:
            assert b"Not generated yet" in resp.read()
        (isolated / "demo").mkdir()
        (isolated / "demo" / "comparison.html").write_text("<html>fixture comparison</html>")
        with urllib.request.urlopen(f"{base}/demo/pr2", timeout=5) as resp:
            assert b"fixture comparison" in resp.read()
        with urllib.request.urlopen(f"{base}/", timeout=5) as resp:
            page = resp.read()
            assert b"PR2 memory demonstration (fixtures)" in page and b"Show possible next pages" in page
            assert b"Base relationship profiles for this page (40)" in page

        monkeypatch.setattr(reader_server, "OFFER_DISPATCH_FACTORY", reader_server._default_offer_dispatch_factory)
        _view("PR2")
        request = urllib.request.Request(
            f"{base}/api/offers", data=json.dumps({"page": "PR2", "request_id": "http-1"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(request, timeout=5)
        payload = json.loads(excinfo.value.read())
        assert excinfo.value.code == 503 and payload["state"] == "error" and payload["request_id"] == "http-1"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_browser_never_places_corpus_text_with_inner_html():
    source = (reader_server.STATIC_DIR / "app.js").read_text()
    assert "innerHTML" not in source and "insertAdjacentHTML" not in source
    assert "no eligible destination" not in source  # the conflated abstention sentence is gone


# --- reviewer-confirmed defects: offers position check, legacy /api/follow, /api/review, wording ---

def test_offers_are_refused_and_nothing_is_dispatched_when_the_log_says_the_reader_is_elsewhere(isolated, monkeypatch):
    # OFFERS_BUILDER / OFFER_DISPATCH_FACTORY are the autouse must-not-dispatch fakes.
    with pytest.raises(ApiError, match="no recorded visit to 'PR2'") as excinfo:
        Handlers.post_offers({"page": "PR2", "request_id": "nowhere"})
    assert excinfo.value.status == 409
    _view("LF3")
    with pytest.raises(ApiError, match="This tab shows 'PR2', but the reading session was last recorded on 'LF3'") as excinfo:
        Handlers.post_offers({"page": "PR2", "request_id": "elsewhere"})
    assert excinfo.value.status == 409 and excinfo.value.payload["state"] == "error"
    assert excinfo.value.payload["position_conflict"] == {"field": "full-41", "this_page": "PR2", "logged_page": "LF3"}
    assert "reload" not in str(excinfo.value)  # a reload would move THIS tab to the other tab's page
    lines = _outcome_lines(isolated)
    assert [line["state"] for line in lines] == ["error", "error"] and lines[1]["request_id"] == "elsewhere"  # persisted


def _accepted_bond(isolated, fake_jev):
    record = _select()
    proposal_id = Handlers.post_propose({"run_dir": record["run_dir"]})["proposal_id"]
    return Handlers.post_accept({"proposal_id": proposal_id})["bond_id"]


def test_legacy_follow_requires_from_page_and_refuses_when_the_reader_is_elsewhere(isolated, fake_jev):
    bond_id = _accepted_bond(isolated, fake_jev)
    with pytest.raises(ApiError, match="missing 'from_page'"):
        Handlers.post_follow({"bond_id": bond_id})
    _view("P3")  # the reviewer's reproduction: the reader is on P3, the bond starts at PR1
    for body in ({"bond_id": bond_id, "from_page": "P3"}, {"bond_id": bond_id, "from_page": "PR1"}):
        with pytest.raises(ApiError) as excinfo:
            Handlers.post_follow(body)
        assert excinfo.value.status == 409
    assert state.reader_state(data_dir=isolated / "data")["history"] == []
    assert "q_traversal" not in [e["event"] for e in _events(isolated)]


def test_legacy_follow_replay_is_one_traversal_and_logs_the_same_events(isolated, fake_jev):
    bond_id = _accepted_bond(isolated, fake_jev)
    _view("PR1")
    first = Handlers.post_follow({"bond_id": bond_id, "from_page": "PR1"})
    second = Handlers.post_follow({"bond_id": bond_id, "from_page": "PR1"})  # replay, no token supplied
    assert first["duplicate"] is False and second["duplicate"] is True
    assert first["active_passage"] == "PR4" and len(second["history"]) == 1
    names = [e["event"] for e in _events(isolated)]
    assert names.count("q_traversal") == 1 and names[-3:] == ["accept_and_follow", "q_traversal", "page_viewed"]
    assert names.index("operator_proposed") < names.index("offer_accepted") < names.index("q_traversal")
    viewed = _events(isolated)[-1]
    assert viewed["page_id"] == "PR4" and viewed["via"] == "traversal"  # the log and reader_state agree
    assert Handlers.get_reader_state({})["last_viewed"]["page_id"] == "PR4"


def test_legacy_follow_validates_page_versions(isolated, fake_jev):
    record = _select()
    proposal_id = Handlers.post_propose({"run_dir": record["run_dir"]})["proposal_id"]
    bond_id = Handlers.post_accept({"proposal_id": proposal_id})["bond_id"]
    bonds_path = isolated / "data" / "bonds.json"
    bonds = json.loads(bonds_path.read_text())
    bonds[bond_id]["destination_sha256"] = "0" * 64
    bonds_path.write_text(json.dumps(bonds))
    with pytest.raises(ApiError, match="has changed") as excinfo:
        Handlers.post_follow({"bond_id": bond_id, "from_page": "PR1"})
    assert excinfo.value.status == 409


def test_review_notes_are_only_written_inside_the_recorded_runs_directory(isolated, tmp_path, fake_jev):
    outside = tmp_path / "elsewhere" / "run"
    outside.mkdir(parents=True)
    (outside / "input.json").write_text("{}")
    for body in ({}, {"run_dir": ""}, {"run_dir": str(outside), "decision": "accept"},
                 {"run_dir": str(isolated / "runs" / ".." / "elsewhere" / "run"), "decision": "accept"}):
        with pytest.raises(ApiError):
            Handlers.post_review(body)
    assert not (outside / "review.json").exists()
    record = _select()
    assert Handlers.post_review({"run_dir": record["run_dir"], "decision": "accept"})["decision"] == "accept"


def test_offer_wording_from_real_build_offers_output_for_failed_requests_and_an_empty_shortlist(tmp_path, monkeypatch):
    helpers = pytest.importorskip("test_memory_helpers")
    from gibsey_lab.memory import contextual, offers as memory_offers

    monkeypatch.setattr(contextual, "ASSESSMENTS_PATH", tmp_path / "contextual" / "assessments.jsonl")
    monkeypatch.setattr(memory_offers, "OFFER_SETS_PATH", tmp_path / "contextual" / "offer_sets.jsonl")
    field = helpers.make_field()

    def build(scores, dispatch):
        return memory_offers.build_offers(
            field, "PR2", [], policy="discovery", dispatch=dispatch, mode="mock", requested_model="m",
            profiles_provider=lambda source, mode: helpers.make_rows(field, "PR2", scores),
            atlas_config_provider=helpers.atlas_config, persist=False)

    failed = build({"LF2": {"contradiction": 1.0}, "PR5": {"development": 0.9}}, helpers.ScriptedDispatch(lambda request: "error"))
    assert failed["state"] == "error" and isinstance(failed["errors"][0], dict)
    message = outcomes.describe_offer_outcome(failed)
    assert "all 2 contextual requests failed (first error: simulated transport failure)" in message
    assert "{" not in message and "destination_id" not in message  # a sentence, never a Python dict

    empty = build({}, helpers.ScriptedDispatch())
    assert empty["state"] == "no_qualified" and empty["state_detail"] == "empty_shortlist"
    message = outcomes.describe_offer_outcome(empty)
    assert "BASE relationship profile cleared the shortlist floors" in message and "nothing was sent for contextual assessment" in message
    assert "0 contextually assessed" not in message

    none_cleared = build({"LF2": {"contradiction": 1.0}}, helpers.ScriptedDispatch(
        lambda request: {"works_after_history": 0.0, "grounded_reading_effect": 0.0, "repeats_recent_reading": 3.0}))
    assert none_cleared["state_detail"] == "none_cleared_thresholds"
    assert "none of the 1 contextually assessed pages cleared the thresholds" in outcomes.describe_offer_outcome(none_cleared)
