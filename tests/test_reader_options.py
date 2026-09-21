"""Exploration repair: an operator click shows ranked destinations from the saved atlas
(no provider call, never an empty panel); weak fits are labeled and still followable;
history refinement never removes an option and any failure keeps the base order, labeled
as such; the single-pick Choice request is a secondary research action whose abstention
never hides the options. tmp_path + fakes only: no live call, no real data/, never 8765."""
import json
import threading
import time

import pytest

from gibsey_lab import jev_client, runner, session_log, state
from gibsey_lab.config import Config
from gibsey_lab.fields import load_field
from gibsey_lab.reader import outcomes
from gibsey_lab.reader import server as reader_server
from gibsey_lab.reader.server import ApiError, Handlers
from gibsey_lab.results import ChoiceResult

DIMS = ("direct_q_fit", "echo", "development", "contradiction", "bridge_relation", "redundancy", "missing_context")
OPERATOR_DIMENSIONS = {"ECHO": "echo", "DEVELOP": "development", "CONTRADICT": "contradiction", "BRIDGE": "bridge_relation"}
EXPLORATORY_LABEL = "Exploratory — weak or uncertain fit"


def _must_not_dispatch(*_args, **_kwargs):
    raise AssertionError("provider work was dispatched where none is allowed")


def fake_options(field, page_id, operator, *, policy, mode, destinations=None, supported=1, unusable=()):
    """A contract-shaped `operator-options/1` dict: `supported` supported rows, the rest exploratory."""
    eligible = field.eligible_candidate_ids(page_id, policy)
    chosen = list(destinations) if destinations is not None else [d for d in eligible if d not in unusable][:3]
    dimension = OPERATOR_DIMENSIONS[operator]
    options = []
    for rank, dest in enumerate(chosen, start=1):
        is_supported = rank <= supported
        norm = 0.9 if is_supported else 0.2
        options.append({
            "destination_id": dest, "destination_sha256": field.manifest[dest].sha256 if dest in field.manifest else "0" * 64,
            "tier": "supported" if is_supported else "exploratory",
            "tier_label": "Supported" if is_supported else EXPLORATORY_LABEL,
            "operator_fit": {"dimension": dimension, "score": norm * 3, "score_norm": norm, "confidence": 0.8,
                             "nearest_level": round(norm * 3)},
            "cautions": [] if is_supported else ["low_direct_q_fit"],
            "base": {d: {"score": 1.0, "score_norm": 1 / 3, "confidence": 0.8} for d in DIMS},
            "assessment_id": f"as-{page_id}-{dest}", "is_authored_neighbor": False, "rank": rank, "rank_reasons": ["r"],
        })
    return {
        "schema": "operator-options/1", "policy_version": "operator-options-v1",
        "option_set_id": f"opts_{page_id}_{operator}_{policy}_{'-'.join(chosen)}", "field": field.id, "page_id": page_id,
        "page_sha256": field.manifest[page_id].sha256, "operator": operator, "dimension": dimension, "policy": policy,
        "mode": mode, "atlas_config_id": "cfg-test", "ordering_basis": "base_assessments", "support_floor": 2 / 3,
        "counts": {"eligible": len(eligible), "usable": len(eligible) - len(unusable), "unusable": len(unusable),
                   "supported": min(supported, len(chosen)), "exploratory_shown": max(len(chosen) - supported, 0),
                   "ineligible_policy": 40 - len(eligible)},
        "unusable": [{"destination_id": d, "status": "unassessed"} for d in unusable],
        "state": "options" if len(chosen) >= 3 else ("no_candidates" if not chosen else "fewer_than_three_eligible"),
        "options": options,
    }


def fake_refiner(mode="ok", delay=0.0, calls=None, reverse=True):
    def refine(option_set, field, events, *, dispatch, mode_=None, requested_model=None, intention=None, **kwargs):
        if calls is not None:
            calls.append({"events": events, "dispatch": dispatch, **kwargs})
        if delay:
            time.sleep(delay)
        if mode == "raise":
            raise RuntimeError("budget_refused: reader allowance spent")
        from gibsey_lab.memory.packet import build_memory_packet, memory_sha256

        packet = build_memory_packet(field, option_set["page_id"], events, candidate_policy=option_set["policy"], intention=intention)
        refined = json.loads(json.dumps(option_set))
        refined["refinement"] = {"state": mode, "errors": [], "memory_sha256": memory_sha256(packet), "assessed_ids": []}
        for index, option in enumerate(refined["options"]):
            if mode == "ok" or (mode == "partial" and index == 0):
                option["contextual"] = {"answers": {"works_after_history": {"score": 1.0 + index, "confidence": 0.7}}}
                refined["refinement"]["assessed_ids"].append(option["destination_id"])
            else:
                option["contextual_error"] = "simulated transport failure"
                refined["refinement"]["errors"].append({"destination_id": option["destination_id"], "status": "error",
                                                        "message": "simulated transport failure"})
        if mode == "ok":
            refined["ordering_basis"] = "reading_history"
            if reverse:
                refined["options"].reverse()
        return refined

    def adapter(option_set, field, events, *, dispatch, mode, requested_model, intention):
        return refine(option_set, field, events, dispatch=dispatch, requested_model=requested_model, intention=intention)

    return adapter


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name, value in (("DATA_DIR", tmp_path / "data"), ("RUNS_DIR", tmp_path / "runs"),
                        ("SESSION_LOG_PATH", tmp_path / "session_log.jsonl"),
                        ("OUTCOMES_PATH", tmp_path / "data" / "reader_outcomes.jsonl"),
                        ("OFFER_SETS_PATH", tmp_path / "data" / "reader_offer_sets.jsonl"),
                        ("OPTION_SETS_PATH", tmp_path / "data" / "reader_option_sets.jsonl"),
                        ("DEMO_DIR", tmp_path / "demo")):
        monkeypatch.setattr(reader_server, name, value)
    monkeypatch.setattr(reader_server, "load_config", lambda: Config(model="jev-latest", api_key="test-key-not-real"))
    monkeypatch.setattr(reader_server, "OPTIONS_PROVIDER", fake_options)
    monkeypatch.setattr(reader_server, "OPTIONS_REFINER", _must_not_dispatch)
    monkeypatch.setattr(reader_server, "OFFERS_BUILDER", _must_not_dispatch)
    monkeypatch.setattr(reader_server, "OFFER_DISPATCH_FACTORY", _must_not_dispatch)
    monkeypatch.setattr(reader_server, "run_case", _must_not_dispatch)
    monkeypatch.setattr(jev_client, "run_choice", _must_not_dispatch)
    monkeypatch.setattr(runner, "RETRY_SLEEP_SECONDS", 0.0)
    monkeypatch.setattr(reader_server, "FLIGHTS", reader_server.SingleFlight())
    reader_server._LATEST_REQUEST.clear()
    return tmp_path


def _view(page, via="dropdown", event="page_viewed"):
    Handlers.post_session_navigation({"event": event, "field": "full-41", "page_id": page, "via": via})


def _options(page="P1", operator="DEVELOP", policy="discovery"):
    return Handlers.get_operator_options({"field": ["full-41"], "page": [page], "operator": [operator], "policy": [policy]})


def _events(tmp_path):
    return session_log.read_events(tmp_path / "session_log.jsonl")


def _outcome_lines(tmp_path):
    return outcomes.read_outcomes(tmp_path / "data" / "reader_outcomes.jsonl")


def _enable_refiner(monkeypatch, refiner):
    monkeypatch.setattr(reader_server, "OPTIONS_REFINER", refiner)
    monkeypatch.setattr(reader_server, "OFFER_DISPATCH_FACTORY", lambda: ("fake-dispatch", "mock", "mock-model"))


# --- operator click: ranked options, no dispatch, even next to a recorded abstention ---

def _write_abstaining_choice_run(runs_dir, page="P1", operator="DEVELOP"):
    field = load_field("full-41")
    order = field.eligible_candidate_ids(page, "discovery") + ["NONE"]
    criterion = __import__("gibsey_lab.relational_operators", fromlist=["CRITERIA"]).CRITERIA[operator]
    run_id = f"20260921T010101Z_reader-full-41-{page}-{operator.lower()}-v0.2-discovery_live"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "input.json").write_text(json.dumps({
        "run_id": run_id, "case_id": run_id.split("_", 1)[1].rsplit("_", 1)[0], "source_id": page, "active_id": None,
        "criterion": criterion, "option_order": order, "options": {},
        "reader_state": {"app": "reader", "field": "full-41", "operator": operator, "policy": "discovery", "criteria_version": "v0.2"},
        "corpus_hashes": {pid: p.sha256 for pid, p in field.manifest.items()},
    }))
    (run_dir / "response.json").write_text(json.dumps({"live": True, "requested_model": "jev-latest", "returned_model": "jev-1.13.0"}))
    (run_dir / "result.json").write_text(json.dumps({"is_abstention": True, "selected_id": None, "selected_text": None,
                                                     "confidence": 0.15, "probabilities": {}}))


def test_operator_click_returns_three_ranked_options_even_when_the_recorded_choice_abstained(isolated):
    """The reproduced defect: P1 DEVELOP had a recorded NONE, so the panel was empty."""
    _write_abstaining_choice_run(isolated / "runs")
    saved = Handlers.get_saved_result({"field": ["full-41"], "source": ["P1"], "operator": ["DEVELOP"]})
    assert saved["recorded"] is True and saved["state"] == "abstained"  # the abstention is still on record ...

    view = _options("P1", "DEVELOP")  # ... and the operator click shows options regardless (no dispatch: autouse fakes)
    assert view["state"] == "options" and len(view["options"]) >= 3
    assert len({o["destination_id"] for o in view["options"]}) == len(view["options"])
    assert view["ordering_line"] == "Ordering: base atlas assessments (not yet compared with your reading history)"
    field = load_field("full-41")
    for option in view["options"]:
        assert view["reader_display"][option["destination_id"]]["text"] == field.manifest[option["destination_id"]].text
    assert {o["tier_label"] for o in view["options"]} == {"Supported", EXPLORATORY_LABEL}

    listed = Handlers.get_outcomes({"page": ["P1"], "operator": ["DEVELOP"], "policy": ["discovery"]})
    assert [o["state"] for o in listed["outcomes"]] == ["abstained"]  # listed beneath, never instead of, the options
    assert not (isolated / "data" / "reader_outcomes.jsonl").exists()  # an operator click is not a request outcome


def test_every_operator_gets_options_and_the_click_is_logged_without_becoming_an_encounter(isolated):
    _view("PR4")
    for operator in ("ECHO", "DEVELOP", "CONTRADICT", "BRIDGE"):
        assert len(_options("PR4", operator)["options"]) >= 3
    shown = [e for e in _events(isolated) if e["event"] == "operator_options_shown"]
    assert [e["operator"] for e in shown] == ["ECHO", "DEVELOP", "CONTRADICT", "BRIDGE"]
    assert session_log.last_encounter(isolated / "session_log.jsonl")["page_id"] == "PR4"
    from gibsey_lab.memory.packet import encounters_from_events

    trace = encounters_from_events(session_log.read_events_with_seq(isolated / "session_log.jsonl"), load_field("full-41"))
    assert [e["page_id"] for e in trace] == ["PR4"]  # looking at options adds nothing to reading memory


def test_option_sets_are_persisted_idempotently(isolated):
    first = _options("P1", "DEVELOP")
    _options("P1", "DEVELOP")
    _options("P1", "ECHO")
    lines = [json.loads(line) for line in (isolated / "data" / "reader_option_sets.jsonl").read_text().splitlines()]
    assert [line["record_type"] for line in lines] == ["option_set", "option_set"]
    assert lines[0]["option_set_id"] == first["option_set_id"]


def test_unusable_pages_and_short_lists_are_said_plainly(isolated, monkeypatch):
    monkeypatch.setattr(reader_server, "OPTIONS_PROVIDER",
                        lambda f, p, o, *, policy, mode: fake_options(f, p, o, policy=policy, mode=mode, unusable=("F1", "F2")))
    assert "2 eligible pages had no usable base assessment and could not be ranked" in _options()["message"]
    monkeypatch.setattr(reader_server, "OPTIONS_PROVIDER",
                        lambda f, p, o, *, policy, mode: fake_options(f, p, o, policy=policy, mode=mode, destinations=["F1"]))
    assert "fewer than three pages are eligible" in _options()["message"]

    def broken(*_a, **_k):
        raise RuntimeError("assessments.jsonl unreadable")

    monkeypatch.setattr(reader_server, "OPTIONS_PROVIDER", broken)
    view = _options()
    assert view["state"] == "atlas_unavailable" and view["options"] == []
    assert "assessments.jsonl unreadable" in view["message"] and "Previous, Next" in view["message"]


def test_operator_options_rejects_bad_requests():
    for query in ({"page": ["P1"]}, {"page": ["P1"], "operator": ["SUMMON"]}, {"page": ["NOPE"], "operator": ["ECHO"]},
                  {"page": ["P1"], "operator": ["ECHO"], "policy": ["whatever"]}):
        with pytest.raises(ApiError):
            Handlers.get_operator_options(query)


# --- following an option ---

def _follow(view, destination, token="tok", from_page=None, **extra):
    return Handlers.post_follow_option({"option_set_id": view["option_set_id"], "destination_id": destination,
                                        "from_page": from_page or view["page_id"], "follow_token": token, **extra})


def test_an_exploratory_option_follows_like_any_other_and_writes_no_review(isolated):
    _view("P1")
    view = _options("P1", "DEVELOP")
    exploratory = next(o for o in view["options"] if o["tier"] == "exploratory")
    before = {p.name for p in (isolated / "data").rglob("*") if p.is_file()}

    outcome = _follow(view, exploratory["destination_id"])
    assert outcome["reader_state"]["active_passage"] == exploratory["destination_id"] and outcome["tier"] == "exploratory"

    data = isolated / "data"
    field = load_field("full-41")
    [proposal] = json.loads((data / "proposals.json").read_text()).values()
    [bond] = json.loads((data / "bonds.json").read_text()).values()
    assert proposal["kind"] == "operator_option" and proposal["status"] == "accepted"
    assert bond["kind"] == "operator_option" and bond["operator"] == "DEVELOP" and bond["tier"] == "exploratory"
    assert bond["option_set_id"] == view["option_set_id"] and bond["operator_fit"] == exploratory["operator_fit"]
    assert bond["source_sha256"] == field.manifest["P1"].sha256
    assert bond["destination_sha256"] == field.manifest[exploratory["destination_id"]].sha256
    [entry] = json.loads((data / "reader_state.json").read_text())["history"]
    assert entry["from_page"] == "P1"

    events = _events(isolated)
    names = [e["event"] for e in events]
    assert names[names.index("operator_proposed"):] == ["operator_proposed", "offer_accepted", "accept_and_follow", "q_traversal", "page_viewed"]
    for event in events[names.index("operator_proposed"):]:
        assert event["operator"] == "DEVELOP" and event["proposal_kind"] == "operator_option"
        assert event["tier"] == "exploratory" and event["option_set_id"] == view["option_set_id"]
        assert event["operator_fit"] == exploratory["operator_fit"]
    assert events[-1]["via"] == "traversal" and events[-1]["page_id"] == exploratory["destination_id"]

    # The reader's explicit choice: no review, judgment, vault entry, or run dir of any kind.
    after = {p.name for p in data.rglob("*") if p.is_file()}
    assert after - before == {"proposals.json", "bonds.json", "reader_state.json"}
    assert not (isolated / "runs").exists() and not list(isolated.rglob("review.json"))
    assert not (data / "gibsey_vault").exists()


def test_double_follow_is_one_traversal(isolated):
    _view("P1")
    view = _options("P1", "DEVELOP")
    destination = view["options"][0]["destination_id"]
    first, second = _follow(view, destination, token="same"), _follow(view, destination, token="same")
    assert first["duplicate"] is False and second["duplicate"] is True
    assert len(second["reader_state"]["history"]) == 1
    assert [e["event"] for e in _events(isolated)].count("q_traversal") == 1


def test_concurrent_double_click_follow_is_one_traversal(isolated):
    _view("P1")
    view = _options("P1", "DEVELOP")
    destination = view["options"][0]["destination_id"]
    results = []
    threads = [threading.Thread(target=lambda: results.append(_follow(view, destination, token="dbl"))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sorted(r["duplicate"] for r in results) == [False, True, True, True]
    assert len(state.reader_state(data_dir=isolated / "data")["history"]) == 1


def test_back_after_a_follow_and_a_repeated_encounter_work_normally(isolated):
    _view("P1")
    view = _options("P1", "DEVELOP")
    destination = view["options"][0]["destination_id"]
    _follow(view, destination, token="a")
    _view("P1", via="back", event="back")
    again = _options("P1", "DEVELOP")  # same page again: same list, followable again with a new token
    assert again["option_set_id"] == view["option_set_id"]
    assert _follow(again, destination, token="b")["duplicate"] is False
    assert len(state.reader_state(data_dir=isolated / "data")["history"]) == 2
    assert [e["event"] for e in _events(isolated)].count("back") == 1  # Back removed nothing


@pytest.mark.parametrize("provider_kwargs,body,status,match", [
    ({}, {"destination_id": "LF9"}, 409, "not one of the options shown"),
    ({"destinations": ["P2", "F1", "F2"]}, {"destination_id": "P2"}, 409, "not eligible"),          # neighbor under discovery
    ({"destinations": ["ZZ9", "F1", "F2"]}, {"destination_id": "ZZ9"}, 409, "not a page in field"),
    ({}, {"destination_id": "F1", "from_page": "PR4"}, 409, "starts from 'P1'"),
    ({}, {"destination_id": "F1", "option_set_id": "opts_unknown"}, 404, "unknown option set"),
])
def test_follow_option_refusals_move_nothing(isolated, monkeypatch, provider_kwargs, body, status, match):
    monkeypatch.setattr(reader_server, "OPTIONS_PROVIDER",
                        lambda f, p, o, *, policy, mode: fake_options(f, p, o, policy=policy, mode=mode, **provider_kwargs))
    view = _options("P1", "DEVELOP")
    request = {"option_set_id": view["option_set_id"], "from_page": "P1", "follow_token": "t", **body}
    with pytest.raises(ApiError, match=match) as excinfo:
        Handlers.post_follow_option(request)
    assert excinfo.value.status == status
    assert not (isolated / "data" / "proposals.json").exists()
    assert state.reader_state(data_dir=isolated / "data")["active_page"] is None
    assert "q_traversal" not in [e["event"] for e in _events(isolated)]


def test_follow_option_is_refused_when_a_page_changed_or_the_reader_is_elsewhere(isolated, monkeypatch):
    view = _options("P1", "DEVELOP")
    path = isolated / "data" / "reader_option_sets.jsonl"
    record = json.loads(path.read_text().splitlines()[0])
    record["option_set"]["options"][0]["destination_sha256"] = "0" * 64
    path.write_text(json.dumps(record) + "\n")
    with pytest.raises(ApiError, match="has changed") as excinfo:
        _follow(view, view["options"][0]["destination_id"])
    assert excinfo.value.status == 409

    _view("LF3")
    with pytest.raises(ApiError, match="last recorded on 'LF3'") as excinfo:
        _follow(view, view["options"][1]["destination_id"])
    assert excinfo.value.status == 409
    assert excinfo.value.payload["position_conflict"] == {"field": "full-41", "this_page": "P1", "logged_page": "LF3"}
    assert state.reader_state(data_dir=isolated / "data")["history"] == []


# --- refinement ---

def test_refinement_reorders_without_removing_and_labels_the_basis(isolated, monkeypatch):
    calls = []
    _view("PR1")
    _view("P1", via="dropdown")
    view = _options("P1", "DEVELOP")
    _enable_refiner(monkeypatch, fake_refiner("ok", calls=calls))
    refined = Handlers.post_refine_options({"option_set_id": view["option_set_id"], "request_id": "rf-1"})
    assert refined["refine_state"] == "refined" and refined["request_id"] == "rf-1" and refined["applicable"] is True
    assert refined["ordering_basis"] == "reading_history" and refined["memory_current"] is True
    assert refined["ordering_line"] == "Ordering: your reading history (1 encounter supplied)" and refined["order_changed"] is True
    assert [o["destination_id"] for o in refined["options"]] == [o["destination_id"] for o in reversed(view["options"])]
    assert [o["tier"] for o in refined["options"]] == [o["tier"] for o in reversed(view["options"])]  # tiers unchanged
    assert calls[0]["dispatch"] == "fake-dispatch" and [e["seq"] for e in calls[0]["events"]][:2] == [0, 1]
    [line] = _outcome_lines(isolated)
    assert line["kind"] == "options_refinement" and line["state"] == "refined" and line["operator"] == "DEVELOP"
    listed = Handlers.get_outcomes({"page": ["P1"], "operator": ["DEVELOP"], "kind": ["options_refinement"]})
    assert [o["state"] for o in listed["outcomes"]] == ["refined"]
    assert Handlers.get_outcomes({"page": ["P1"], "operator": ["DEVELOP"]})["count"] == 0  # not mixed into single picks
    # a refined list is followed through the same stored base set
    assert _follow(view, refined["options"][0]["destination_id"])["duplicate"] is False


@pytest.mark.parametrize("mode,state_id", [("partial", "refine_partial"), ("failed", "refine_failed")])
def test_a_failed_or_partial_refinement_keeps_every_option_in_base_order_and_says_so(isolated, monkeypatch, mode, state_id):
    _view("P1")
    view = _options("P1", "DEVELOP")
    _enable_refiner(monkeypatch, fake_refiner(mode))
    result = Handlers.post_refine_options({"option_set_id": view["option_set_id"]})
    assert result["refine_state"] == state_id and result["ordering_basis"] == "base_assessments"
    assert [o["destination_id"] for o in result["options"]] == [o["destination_id"] for o in view["options"]]
    assert "NOT newly assessed against your reading history" in result["ordering_line"]
    assert "base order is kept" in result["refine_message"] and "try again" in result["refine_message"]
    assert "simulated transport failure" in result["refine_message"]
    assert _outcome_lines(isolated)[0]["state"] == state_id
    # still followable, and a retry is possible
    _enable_refiner(monkeypatch, fake_refiner("ok"))
    assert Handlers.post_refine_options({"option_set_id": view["option_set_id"]})["refine_state"] == "refined"
    assert _follow(view, view["options"][2]["destination_id"])["duplicate"] is False


def test_a_refiner_exception_or_budget_refusal_is_persisted_and_the_options_survive(isolated, monkeypatch):
    _view("P1")
    view = _options("P1", "DEVELOP")
    _enable_refiner(monkeypatch, fake_refiner("raise"))
    with pytest.raises(ApiError, match="budget_refused") as excinfo:
        Handlers.post_refine_options({"option_set_id": view["option_set_id"], "request_id": "rf-x"})
    payload = excinfo.value.payload
    assert excinfo.value.status == 500 and payload["refine_state"] == "error" and payload["request_id"] == "rf-x"
    assert [o["destination_id"] for o in payload["options"]] == [o["destination_id"] for o in view["options"]]
    assert "NOT newly assessed" in payload["ordering_line"]
    assert _outcome_lines(isolated)[0]["state"] == "error"
    assert _options("P1", "DEVELOP")["state"] == "options"  # the list is untouched


def test_a_refinement_that_drops_an_option_is_discarded(isolated, monkeypatch):
    _view("P1")
    view = _options("P1", "DEVELOP")

    def dropping(option_set, field, events, **_k):
        return {**option_set, "options": option_set["options"][:2], "ordering_basis": "reading_history"}

    _enable_refiner(monkeypatch, dropping)
    with pytest.raises(ApiError, match="discarded") as excinfo:
        Handlers.post_refine_options({"option_set_id": view["option_set_id"]})
    assert len(excinfo.value.payload["options"]) == 3


def test_a_stale_refinement_is_persisted_but_flagged_not_applicable(isolated, monkeypatch):
    _view("P1")
    view = _options("P1", "DEVELOP")
    _enable_refiner(monkeypatch, fake_refiner("ok", delay=0.4))
    results = {}
    worker = threading.Thread(target=lambda: results.update(r=Handlers.post_refine_options({"option_set_id": view["option_set_id"]})))
    worker.start()
    time.sleep(0.1)
    _view("LF3")  # the reader navigates away before the response
    worker.join(10)
    assert results["r"]["refine_state"] == "refined" and results["r"]["applicable"] is False
    assert "LF3" in results["r"]["not_applicable_reason"]
    [line] = _outcome_lines(isolated)
    assert line["applicable"] is False and line["state"] == "refined"  # persisted, to be ignored by the browser


def test_refinement_is_single_flight_and_refused_when_the_reader_is_elsewhere(isolated, monkeypatch):
    calls = []
    view = _options("P1", "DEVELOP")
    _enable_refiner(monkeypatch, fake_refiner("ok", delay=0.3, calls=calls))
    with pytest.raises(ApiError) as excinfo:  # no page_viewed for P1 in the log: nothing is dispatched
        Handlers.post_refine_options({"option_set_id": view["option_set_id"]})
    assert excinfo.value.status == 409 and calls == []

    _view("P1")
    results = {}
    threads = [threading.Thread(target=lambda rid=rid: results.update({rid: Handlers.post_refine_options(
        {"option_set_id": view["option_set_id"], "request_id": rid})})) for rid in ("a", "b")]
    threads[0].start()
    time.sleep(0.1)
    threads[1].start()
    for t in threads:
        t.join(10)
    assert len(calls) == 1 and results["a"]["request_id"] == "a" and results["b"]["request_id"] == "b"


# --- the single pick stays a separate research action ---

def test_a_single_pick_abstention_is_recorded_and_the_options_are_unaffected(isolated, monkeypatch):
    from gibsey_lab.runner import run_case

    monkeypatch.setattr(reader_server, "run_case", run_case)
    monkeypatch.setattr(jev_client, "run_choice", lambda cfg, *, state, instructions, criteria: ChoiceResult(
        requested_model=cfg.model, returned_model="fake", choice="NONE", confidence=0.14, probabilities={"NONE": 0.14}, live=True))
    _view("P6")
    before = _options("P6", "DEVELOP")
    pick = Handlers.post_request_selection({"field": "full-41", "source": "P6", "operator": "DEVELOP", "policy": "discovery"})
    assert pick["state"] == "abstained"
    after = _options("P6", "DEVELOP")
    assert after["option_set_id"] == before["option_set_id"] and len(after["options"]) >= 3
    assert _follow(after, after["options"][0]["destination_id"])["duplicate"] is False


# --- reload, build identity, static hooks ---

def test_reader_state_names_the_operator_list_open_on_the_current_page_only(isolated):
    _view("P1")
    _options("P1", "CONTRADICT")
    assert Handlers.get_reader_state({})["last_operator_options"] == {
        "field": "full-41", "page_id": "P1", "operator": "CONTRADICT", "policy": "discovery"}
    _view("P1", via="reload")  # a refresh keeps it
    assert Handlers.get_reader_state({})["last_operator_options"]["operator"] == "CONTRADICT"
    _view("P2", via="next")
    assert Handlers.get_reader_state({})["last_operator_options"] is None
    _view("P1", via="back", event="back")  # a later visit starts clean
    assert Handlers.get_reader_state({})["last_operator_options"] is None


def test_build_identity_matches_the_served_app_js():
    import hashlib

    build = Handlers.get_build({})
    assert set(build) == {"git_revision", "dirty", "app_js_sha256", "server_started_at"}
    assert build["app_js_sha256"] == hashlib.sha256((reader_server.STATIC_DIR / "app.js").read_bytes()).hexdigest()


def test_static_page_has_the_acceptance_hooks_and_no_auto_dispatch_on_operator_click():
    html = (reader_server.STATIC_DIR / "index.html").read_text()
    js = (reader_server.STATIC_DIR / "app.js").read_text()
    for hook in ("options-list", "refine-button", "refine-status", "ordering-line", "source-id", "back-btn",
                 "single-pick-button", "single-pick-status", "build-id"):
        assert f'data-testid="{hook}"' in html, hook
    for hook in ("option-row", "option-preview", "option-preview-text", "option-follow", "operator-${op}"):
        assert hook in js, hook
    assert "Advanced: history-conditioned hand" in html and "Ask Jev for a single pick (research)" in html
    select = js[js.index("async function selectOperator("):js.index("async function loadOptions(")]
    assert "request-selection" not in select and "requestSelection" not in select and "saved-result" not in select
    assert "innerHTML" not in js


# --- QA-confirmed defects: truthful refinement wording, level words, second tab ---

def test_a_refinement_that_does_not_change_the_order_never_claims_a_history_ordering(isolated, monkeypatch):
    _view("PR1")
    _view("P1")
    view = _options("P1", "DEVELOP")
    _enable_refiner(monkeypatch, fake_refiner("ok", reverse=False))  # every answer valid, order identical to base
    result = Handlers.post_refine_options({"option_set_id": view["option_set_id"]})
    assert result["refine_state"] == "refined" and result["ordering_basis"] == "reading_history"  # as the refiner returned it
    assert result["order_changed"] is False
    assert [o["destination_id"] for o in result["options"]] == [o["destination_id"] for o in view["options"]]
    line = result["ordering_line"]
    assert line.startswith("Ordering: base atlas order") and "assessed for all 3 options (1 encounter supplied)" in line
    assert "did not change the order" in line and not line.startswith("Ordering: your reading history")
    assert "did not change the order" in result["refine_message"] and "base atlas order" in result["refine_message"]
    assert "no support" not in line
    assert _outcome_lines(isolated)[0]["order_changed"] is False


def test_all_weakest_history_answers_say_jev_found_no_support_and_options_stay(isolated, monkeypatch):
    _view("P1")
    view = _options("P1", "DEVELOP")

    def weakest(option_set, field, events, **_k):
        refined = fake_refiner("ok", reverse=False)(option_set, field, events, dispatch=None, mode="mock",
                                                    requested_model="m", intention=None)
        for option in refined["options"]:
            option["contextual"]["answers"]["works_after_history"]["score"] = 0.2
        return refined

    _enable_refiner(monkeypatch, weakest)
    result = Handlers.post_refine_options({"option_set_id": view["option_set_id"]})
    assert result["order_changed"] is False and result["history_found_no_support"] is True
    assert "Jev found no support in this history for any of these moves" in result["ordering_line"]
    assert "every option stays available" in result["ordering_line"] and len(result["options"]) == 3


def test_ordering_wording_table():
    three = {"ordering_basis": "reading_history", "options": [{}, {}, {}]}
    changed = outcomes.describe_ordering(three, encounters_supplied=6, refine_state="refined", order_changed=True)
    same = outcomes.describe_ordering(three, encounters_supplied=6, refine_state="refined", order_changed=False)
    none = outcomes.describe_ordering(three, encounters_supplied=6, refine_state="refined", order_changed=False, no_support=True)
    assert changed == "Ordering: your reading history (6 encounters supplied)"
    assert same == ("Ordering: base atlas order \u2014 your reading history was assessed for all 3 options "
                    "(6 encounters supplied) but did not change the order.")
    assert none.startswith(same) and "no support" in none
    assert outcomes.describe_ordering({"ordering_basis": "base_assessments"}) == outcomes.ORDERING_BASE
    assert outcomes.history_found_no_support([{"contextual": {"answers": {"works_after_history": {"score": 0.49}}}}]) is True
    assert outcomes.history_found_no_support([{"contextual": {"answers": {"works_after_history": {"score": 0.5}}}}]) is False
    assert outcomes.history_found_no_support([{}]) is False and outcomes.history_found_no_support([]) is False


def test_level_words_come_from_the_level_a_score_clears_so_tiers_never_share_a_word():
    assert [outcomes.level_cleared(s) for s in (0.0, 0.99, 1.0, 1.5, 1.99, 2.0, 2.49, 2.5, 3.0)] == [0, 0, 1, 1, 1, 2, 2, 3, 3]
    assert outcomes.level_cleared(None) is None and outcomes.level_name("echo", None) is None
    for dimension in OPERATOR_DIMENSIONS.values():
        exploratory_words = {outcomes.level_name(dimension, s / 100) for s in range(0, 200)}  # below the support floor
        supported_words = {outcomes.level_name(dimension, s / 100) for s in range(200, 301)}
        assert not exploratory_words & supported_words, dimension
    assert outcomes.level_name("development", 1.75) == "slight development"  # was "moderate", the same word as 2.3
    assert outcomes.level_name("development", 2.3) == "definite development"
    assert outcomes.level_name("echo", 2.6) == "strong recurrence"
    assert outcomes.level_name("not_a_dimension", 1.75) == "slight"


def test_option_rows_carry_the_level_word_without_touching_the_numbers(isolated):
    view = _options("P1", "DEVELOP")
    supported, exploratory = view["options"][0], view["options"][-1]
    assert supported["fit_level"] == {"level_cleared": 3, "name": "strong development"}
    assert exploratory["fit_level"] == {"level_cleared": 0, "name": "no development"}
    assert exploratory["operator_fit"]["score"] == pytest.approx(0.6)  # the recorded number is untouched


def test_a_second_tab_conflict_names_both_pages_and_resuming_here_makes_the_action_possible(isolated, monkeypatch):
    _view("P1")
    view = _options("P1", "DEVELOP")
    _view("LF3")  # another tab moved on
    _enable_refiner(monkeypatch, fake_refiner("ok"))
    with pytest.raises(ApiError) as excinfo:
        Handlers.post_refine_options({"option_set_id": view["option_set_id"]})
    assert excinfo.value.status == 409 and "reload" not in str(excinfo.value)
    assert "'P1'" in str(excinfo.value) and "'LF3'" in str(excinfo.value)
    assert excinfo.value.payload["position_conflict"]["logged_page"] == "LF3"
    assert [o["destination_id"] for o in excinfo.value.payload["options"]] == [o["destination_id"] for o in view["options"]]
    assert state.reader_state(data_dir=isolated / "data")["history"] == []  # nothing moved

    _view("P1", via="resume")  # "Continue here on P1": an explicit, logged choice
    assert _events(isolated)[-1]["via"] == "resume"
    assert Handlers.post_refine_options({"option_set_id": view["option_set_id"]})["refine_state"] == "refined"
    assert _follow(view, view["options"][0]["destination_id"])["duplicate"] is False


def test_static_page_offers_the_two_honest_choices_for_a_second_tab_and_never_a_reload():
    html = (reader_server.STATIC_DIR / "index.html").read_text()
    js = (reader_server.STATIC_DIR / "app.js").read_text()
    server_source = (reader_server.STATIC_DIR.parent / "server.py").read_text()
    assert 'data-testid="position-conflict"' in html
    for needle in ("conflict-continue-here", "conflict-go-to-other", "Continue here on ", "Go to ", 'via: "resume"', "orderChanged"):
        assert needle in js, needle
    assert "reload the page" not in js and "reload the page" not in server_source
    assert "moderate" not in js  # level words come from the rubric level the score clears
