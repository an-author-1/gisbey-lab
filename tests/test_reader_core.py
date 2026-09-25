"""Reader integration of Core v0.3 (contract R): /api/core/session|options|execute|status|
journey|pause|resume, the legacy-store projector, and the read-only journey page.

tmp_path only: DATA_DIR, SESSION_LOG_PATH and CORE_DIR are monkeypatched, so the real
data/ (and the real data/core/, which must not be created here) is never touched. The real
live atlas is read, read-only, for the offered bonds. No provider is ever called: every
dispatch hook is replaced by an assertion.
"""
import glob
import hashlib
import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from gibsey_lab import jev_client, session_log, state
from gibsey_lab.config import Config
from gibsey_lab.core import identity, journal, projectors, reducer
from gibsey_lab.core.core import Core
from gibsey_lab.corpus import REPO_ROOT
from gibsey_lab.fields import load_field
from gibsey_lab.reader import server as reader_server
from gibsey_lab.reader.server import ApiError, Handlers

FIELD = load_field("full-41")
STATIC = reader_server.STATIC_DIR


def _must_not_dispatch(*_args, **_kwargs):
    raise AssertionError("provider work was dispatched where none is allowed")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name, value in (("DATA_DIR", tmp_path / "data"), ("RUNS_DIR", tmp_path / "runs"),
                        ("SESSION_LOG_PATH", tmp_path / "session_log.jsonl"), ("CORE_DIR", tmp_path / "core"),
                        ("OUTCOMES_PATH", tmp_path / "data" / "reader_outcomes.jsonl"),
                        ("OFFER_SETS_PATH", tmp_path / "data" / "reader_offer_sets.jsonl"),
                        ("OPTION_SETS_PATH", tmp_path / "data" / "reader_option_sets.jsonl"),
                        ("DEMO_DIR", tmp_path / "demo")):
        monkeypatch.setattr(reader_server, name, value)
    monkeypatch.setattr(reader_server, "load_config", lambda: Config(model="jev-latest", api_key="test-key-not-real"))
    monkeypatch.setattr(reader_server, "OPTIONS_REFINER", _must_not_dispatch)
    monkeypatch.setattr(reader_server, "OFFERS_BUILDER", _must_not_dispatch)
    monkeypatch.setattr(reader_server, "OFFER_DISPATCH_FACTORY", _must_not_dispatch)
    monkeypatch.setattr(reader_server, "run_case", _must_not_dispatch)
    monkeypatch.setattr(jev_client, "run_choice", _must_not_dispatch)
    monkeypatch.setattr(reader_server, "FLIGHTS", reader_server.SingleFlight())
    reader_server._LATEST_REQUEST.clear()
    return tmp_path


# --- helpers -----------------------------------------------------------------------------

def _start(page="P1", **extra):
    return Handlers.post_core_session({"page": page, **extra})


def _options(session_id, operator="DEVELOP", policy="discovery"):
    return Handlers.post_core_options({"session_id": session_id, "operator": operator, "policy": policy})


def _execute(session_id, offers, bond, request_id, expected_revision=None):
    return Handlers.post_core_execute({
        "session_id": session_id, "offer_set_id": offers["offer_set_id"], "bond_version_id": bond["bond_version_id"],
        "expected_revision": offers["revision"] if expected_revision is None else expected_revision, "request_id": request_id,
    })


def _journal(tmp_path, session_id):
    return journal.read_events(session_id, tmp_path / "core")


def _log(tmp_path):
    return session_log.read_events(tmp_path / "session_log.jsonl")


def _reader_state(tmp_path):
    return state.reader_state(data_dir=tmp_path / "data")


def _bonds(tmp_path):
    path = tmp_path / "data" / "bonds.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _snapshot(root: Path) -> dict[str, bytes]:
    out = {}
    for path in root.rglob("*"):
        if path.is_file():
            out[str(path.relative_to(root))] = path.read_bytes()
    return out


def _vault_text(page_id: str) -> str:
    hits = [f for f in glob.glob(str(REPO_ROOT / "vault" / "*" / "*.md"))
            if os.path.basename(f).replace(" ", "") == page_id + ".md"]
    assert len(hits) == 1, (page_id, hits)
    return Path(hits[0]).read_text(encoding="utf-8")


def _followed(tmp_path, page="P1", operator="DEVELOP", request_id="req-1"):
    """One committed follow from `page`; returns (session_id, offers, bond, result)."""
    session_id = _start(page)["session_id"]
    offers = _options(session_id, operator)
    bond = offers["bonds"][0]
    return session_id, offers, bond, _execute(session_id, offers, bond, request_id)


# --- session start / resume ------------------------------------------------------------

def test_start_session_at_a_page_then_resume_returns_the_same_state(isolated):
    started = _start("P3")
    assert started["started"] is True and started["resumed"] is False
    assert started["active_page"] == "P3" and started["revision"] == 1 and started["encounter_count"] == 1
    assert started["active_version"] == identity.version_id("P3", FIELD.manifest["P3"].sha256)
    assert started["encounters"][0]["via"] == "start"
    session_id = started["session_id"]

    resumed_get = Handlers.get_core_session({"session_id": [session_id]})
    resumed_post = Handlers.post_core_session({"session_id": session_id})
    assert resumed_get["state"] == started["state"] == resumed_post["state"]
    assert resumed_post["resumed"] is True and resumed_post["started"] is False
    assert len(_journal(isolated, session_id)) == 1  # resuming writes nothing
    # the start is mirrored once as a passive page view; no traversal, no bond, no option set
    assert [e["event"] for e in _log(isolated)] == ["page_viewed"]
    assert _log(isolated)[0]["via"] == "start" and _log(isolated)[0]["session_id"] == session_id
    assert not (isolated / "data" / "reader_option_sets.jsonl").exists()
    assert not (isolated / "data" / "bonds.json").exists()


def test_start_without_a_page_uses_the_readers_last_recorded_page(isolated):
    Handlers.post_session_navigation({"event": "page_viewed", "field": "full-41", "page_id": "LF4", "via": "dropdown"})
    assert Handlers.post_core_session({})["active_page"] == "LF4"


def test_unknown_stored_session_id_starts_a_new_session_with_that_id(isolated):
    view = Handlers.post_core_session({"session_id": "s_forgotten01", "page": "P2"})
    assert view["started"] is True and view["session_id"] == "s_forgotten01" and view["active_page"] == "P2"


def test_unknown_session_on_get_is_404_with_the_core_code(isolated):
    with pytest.raises(ApiError) as e:
        Handlers.get_core_session({"session_id": ["s_nobody000"]})
    assert e.value.status == 404 and e.value.payload["code"] == "unknown_session"


# --- options: pure read + one non-bumping journal event ----------------------------------

def test_options_twice_at_one_revision_is_one_offer_set_one_event_and_no_legacy_writes(isolated):
    session_id = _start("P1")["session_id"]
    log_before = _log(isolated)
    first = _options(session_id)
    second = _options(session_id)
    assert first["offer_set_id"] == second["offer_set_id"]
    assert first["reused"] is False and second["reused"] is True
    assert [b["bond_version_id"] for b in first["bonds"]] == [b["bond_version_id"] for b in second["bonds"]]
    events = _journal(isolated, session_id)
    assert [e["event"] for e in events] == ["session_started", "offer_set_created"]
    assert events[-1]["revision_after"] == 1  # not state-changing
    assert first["revision"] == 1 and first["current_revision"] == 1
    assert _log(isolated) == log_before  # no session-log event
    assert not (isolated / "data" / "reader_option_sets.jsonl").exists()
    assert not (isolated / "data" / "reader_outcomes.jsonl").exists()
    # every bond quotes the destination's exact opening sentence and carries its assessment id
    for bond in first["bonds"]:
        dest = bond["destination_page"]
        assert bond["destination_id"] == dest
        assert bond["wording"] and FIELD.manifest[dest].text.lstrip().startswith(bond["wording"][:20])
        assert bond["wording_source"] == "destination_opening_sentence"
        assert bond["assessment_id"]
        assert bond["fit_level"]["level_cleared"] in (0, 1, 2, 3)
        assert first["reader_display"][dest]["text"] == FIELD.manifest[dest].text
    assert first["ordering_basis"] == "base_assessments" and first["page_id"] == "P1" and first["field"] == "full-41"
    assert "evidence" in first["evidence_note"]


def test_options_match_the_ranked_list_the_legacy_endpoint_shows(isolated):
    session_id = _start("F3")["session_id"]
    core_rows = [(b["destination_id"], b["tier"]) for b in _options(session_id, "ECHO")["bonds"]]
    legacy = Handlers.get_operator_options({"field": ["full-41"], "page": ["F3"], "operator": ["ECHO"], "policy": ["discovery"]})
    assert core_rows == [(o["destination_id"], o["tier"]) for o in legacy["options"]]


# --- execute: commit once, mirror once, deduplicate --------------------------------------

def test_execute_commits_one_event_and_mirrors_the_legacy_stores_exactly_once(isolated):
    session_id, offers, bond, result = _followed(isolated)
    assert result["status"] == "committed" and result["duplicate"] is False
    assert result["to_page"] == bond["destination_page"] and result["revision_after"] == 2
    assert result["projection_errors"] == []
    assert result["session"]["active_page"] == bond["destination_page"] and result["session"]["encounter_count"] == 2
    assert result["reader_state"]["active_page"] == bond["destination_page"]

    events = _journal(isolated, session_id)
    assert [e["event"] for e in events] == ["session_started", "offer_set_created", "action_committed"]
    committed = events[-1]
    assert committed["revision_after"] == 2 and committed["request_id"] == "req-1"
    assert committed["wording"] == bond["wording"]

    bonds = _bonds(isolated)
    assert list(bonds) == [bond["bond_version_id"]]
    entry = bonds[bond["bond_version_id"]]
    assert entry["kind"] == "core" and entry["operator"] == "DEVELOP"
    assert entry["source_version"] == bond["source_version"] and entry["destination_version"] == bond["destination_version"]
    assert entry["source_sha256"] == FIELD.manifest["P1"].sha256
    assert entry["destination_sha256"] == FIELD.manifest[bond["destination_page"]].sha256
    assert entry["wording"] == bond["wording"] and entry["offer_set_id"] == offers["offer_set_id"]
    assert entry["request_id"] == "req-1" and entry["core_event_seq"] == committed["seq"]
    assert entry["target_text"] == FIELD.manifest[bond["destination_page"]].text  # so Preserve keeps working

    history = _reader_state(isolated)["history"]
    assert len(history) == 1
    assert history[0]["event"] == "Q_follow" and history[0]["follow_token"] == "req-1"
    assert history[0]["from_page"] == "P1" and history[0]["to_id"] == bond["destination_page"]
    assert history[0]["from_version"] == bond["source_version"] and history[0]["to_version"] == bond["destination_version"]
    assert history[0]["core_event_seq"] == committed["seq"] and history[0]["session_id"] == session_id

    log = _log(isolated)
    assert [e["event"] for e in log] == ["page_viewed", "operator_proposed", "offer_accepted", "accept_and_follow",
                                         "q_traversal", "page_viewed"]
    for e in log[1:]:
        assert e["session_id"] == session_id and e["core_event_seq"] == committed["seq"]
        assert e["version_id"] == bond["destination_version"] and e["operator"] == "DEVELOP"
        assert e["bond_version_id"] == bond["bond_version_id"] and e["proposal_kind"] == "core_bond"
    assert log[1]["page_sha256"] == FIELD.manifest["P1"].sha256
    assert log[1]["destination_sha256"] == FIELD.manifest[bond["destination_page"]].sha256
    assert log[-1]["via"] == "traversal" and log[-1]["page_id"] == bond["destination_page"]
    assert log[-1]["page_sha256"] == FIELD.manifest[bond["destination_page"]].sha256
    assert [e["seq"] for e in log] == list(range(len(log)))

    # the projector run again over the same events changes nothing
    before = _snapshot(isolated)
    projector = projectors.mirror_to_legacy_stores(isolated / "data", isolated / "session_log.jsonl", field=FIELD)
    projectors.rebuild(session_id, events, projector)
    assert _snapshot(isolated) == before


def test_identical_retry_is_a_recorded_duplicate_with_no_new_event_or_mirror(isolated):
    session_id, offers, bond, first = _followed(isolated)
    before = _snapshot(isolated)
    again = _execute(session_id, offers, bond, "req-1")
    assert again["duplicate"] is True and again["status"] == "committed"
    assert again["bond_version_id"] == bond["bond_version_id"] and again["to_version"] == first["to_version"]
    assert again["state"] == first["state"]
    assert _snapshot(isolated) == before


def test_same_request_id_for_a_different_bond_is_request_id_reused(isolated):
    session_id, offers, bond, _ = _followed(isolated)
    before = _snapshot(isolated)
    with pytest.raises(ApiError) as e:
        _execute(session_id, offers, offers["bonds"][1], "req-1")
    assert e.value.status == 409 and e.value.payload["code"] == "request_id_reused"
    assert e.value.payload["details"]["recorded"]["bond_version_id"] == bond["bond_version_id"]
    assert _snapshot(isolated) == before  # a refusal before validation is not even journaled


def test_stale_expected_revision_is_refused_journaled_and_moves_nothing(isolated):
    session_id = _start("P1")["session_id"]
    offers = _options(session_id)
    before = _snapshot(isolated)
    with pytest.raises(ApiError) as e:
        _execute(session_id, offers, offers["bonds"][0], "req-stale", expected_revision=7)
    assert e.value.status == 409 and e.value.payload["code"] == "stale_revision"
    assert e.value.payload["current_revision"] == 1
    assert e.value.payload["session"]["active_page"] == "P1"
    events = _journal(isolated, session_id)
    assert events[-1]["event"] == "action_rejected" and events[-1]["code"] == "stale_revision"
    assert events[-1]["revision_after"] == 1
    assert Handlers.get_core_session({"session_id": [session_id]})["encounter_count"] == 1
    assert Handlers.get_core_status({"session_id": [session_id], "request_id": ["req-stale"]})["status"] == "rejected"
    after = _snapshot(isolated)
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert changed == {f"core/sessions/{session_id}/events.jsonl"}  # only the journal; no mirrors, no log


def test_a_bond_that_was_not_offered_is_refused(isolated):
    session_id = _start("P1")["session_id"]
    offers = _options(session_id)
    other = _options(session_id, "ECHO")
    foreign = next(b for b in other["bonds"] if b["bond_version_id"] not in offers["bond_version_ids"])
    with pytest.raises(ApiError) as e:
        _execute(session_id, offers, foreign, "req-x")
    assert e.value.status == 409 and e.value.payload["code"] == "not_offered"
    assert Handlers.get_core_session({"session_id": [session_id]})["encounter_count"] == 1
    assert not (isolated / "data" / "bonds.json").exists()


def test_second_tab_execute_after_the_first_moved_is_stale_and_moves_nothing(isolated):
    session_id = _start("P1")["session_id"]
    tab_a = _options(session_id)
    tab_b = _options(session_id)  # same offer set, both tabs at revision 1
    moved = _execute(session_id, tab_a, tab_a["bonds"][0], "tab-a-click")
    before = _snapshot(isolated)
    with pytest.raises(ApiError) as e:
        _execute(session_id, tab_b, tab_b["bonds"][1], "tab-b-click")
    assert e.value.payload["code"] == "stale_revision" and e.value.payload["current_revision"] == 2
    assert e.value.payload["session"]["active_page"] == moved["to_page"]
    view = Handlers.get_core_session({"session_id": [session_id]})
    assert view["encounter_count"] == 2 and view["active_page"] == moved["to_page"]
    after = _snapshot(isolated)
    assert {k for k in after if before.get(k) != after[k]} == {f"core/sessions/{session_id}/events.jsonl"}
    assert len(_reader_state(isolated)["history"]) == 1


def test_two_simultaneous_executes_commit_exactly_one_and_refuse_the_other_cleanly(isolated):
    session_id = _start("P1")["session_id"]
    offers = _options(session_id)
    outcomes_by_thread: dict[str, object] = {}
    gate = threading.Barrier(2)

    def click(name, bond):
        gate.wait()
        try:
            outcomes_by_thread[name] = _execute(session_id, offers, bond, f"click-{name}")
        except ApiError as e:
            outcomes_by_thread[name] = e

    threads = [threading.Thread(target=click, args=("a", offers["bonds"][0])),
               threading.Thread(target=click, args=("b", offers["bonds"][1]))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    committed = [v for v in outcomes_by_thread.values() if isinstance(v, dict)]
    refused = [v for v in outcomes_by_thread.values() if isinstance(v, ApiError)]
    assert len(committed) == 1 and len(refused) == 1
    assert refused[0].status == 409 and refused[0].payload["code"] == "stale_revision"  # never a JournalError 500
    assert Handlers.get_core_session({"session_id": [session_id]})["encounter_count"] == 2
    assert len(_reader_state(isolated)["history"]) == 1


def test_paused_session_refuses_execute_and_options_until_resumed(isolated):
    session_id = _start("P1")["session_id"]
    offers = _options(session_id)
    paused = Handlers.post_core_pause({"session_id": session_id})
    assert paused["paused"] is True and paused["revision"] == 2
    with pytest.raises(ApiError) as e:
        _execute(session_id, offers, offers["bonds"][0], "req-p", expected_revision=2)
    assert e.value.status == 409 and e.value.payload["code"] == "paused"
    with pytest.raises(ApiError) as e2:
        _options(session_id)
    assert e2.value.payload["code"] == "paused"
    resumed = Handlers.post_core_resume({"session_id": session_id})
    assert resumed["paused"] is False and resumed["revision"] == 3
    fresh = _options(session_id)
    assert fresh["revision"] == 3
    result = _execute(session_id, fresh, fresh["bonds"][0], "req-after")
    assert result["revision_after"] == 4 and result["session"]["encounter_count"] == 2


def test_missing_or_malformed_execute_fields_are_400(isolated):
    session_id = _start("P1")["session_id"]
    offers = _options(session_id)
    with pytest.raises(ApiError) as e:
        Handlers.post_core_execute({"session_id": session_id, "offer_set_id": offers["offer_set_id"]})
    assert e.value.status == 400
    with pytest.raises(ApiError) as e2:
        Handlers.post_core_execute({"session_id": session_id, "offer_set_id": offers["offer_set_id"],
                                    "bond_version_id": offers["bonds"][0]["bond_version_id"],
                                    "expected_revision": "1", "request_id": "r"})
    assert e2.value.status == 400


# --- restart, journey, crash recovery ----------------------------------------------------

def test_resume_after_a_simulated_restart_gives_the_identical_state(isolated):
    session_id, offers, bond, result = _followed(isolated, page="P2", operator="BRIDGE")
    second = _options(session_id, "ECHO")
    result2 = _execute(session_id, second, second["bonds"][-1], "req-2")
    before_view = Handlers.get_core_session({"session_id": [session_id]})
    # restart: forget every in-process cache and reduce the journal again with a fresh Core
    journal._LOCKS.clear()
    session_log._LINE_COUNTS.clear()
    fresh = Core(core_dir=isolated / "core", field=load_field("full-41"))
    after = fresh.resume_session(session_id)
    assert after["state"] == before_view["state"] == result2["state"]
    assert after["encounters"] == before_view["encounters"]
    assert [e["page_id"] for e in after["encounters"]] == ["P2", bond["destination_page"], result2["to_page"]]
    assert reducer.reduce(_journal(isolated, session_id)).canonical() == after["state"]
    assert Handlers.get_core_session({"session_id": [session_id]})["state"] == after["state"]


def test_journey_shows_exact_prose_offer_sets_and_state_and_writes_nothing(isolated):
    session_id, offers, bond, _ = _followed(isolated)
    second = _options(session_id, "CONTRADICT")
    chosen = second["bonds"][1]
    _execute(session_id, second, chosen, "req-2")
    before = _snapshot(isolated)
    journey = Handlers.get_core_journey({"session_id": [session_id]})
    assert _snapshot(isolated) == before  # a GET writes nothing
    assert journey["session_id"] == session_id and journey["revision"] == 3 and journey["paused"] is False
    assert journey["field"] == "full-41" and journey["encounter_count"] == 3
    assert journey["atlas_config_ids"] == [offers["atlas_config_id"]]
    encounters = journey["encounters"]
    assert [e["encounter_index"] for e in encounters] == [0, 1, 2]
    for e in encounters:
        assert e["prose"]["current"] is True
        assert e["prose"]["text"] == FIELD.manifest[e["page_id"]].text == _vault_text(e["page_id"])
        assert e["version_id"] == identity.version_id(e["page_id"], e["prose"]["sha256"])
    assert encounters[0]["via"] == "start" and encounters[0]["action"] is None
    first = encounters[1]
    assert first["via"] == "Q"
    action = first["action"]
    assert action["request_id"] == "req-1" and action["bond_version_id"] == bond["bond_version_id"]
    assert action["offer_set"]["offer_set_id"] == offers["offer_set_id"]
    assert [b["bond_version_id"] for b in action["offer_set"]["bonds"]] == offers["bond_version_ids"]
    assert [b["selected"] for b in action["offer_set"]["bonds"]] == [b["bond_version_id"] == bond["bond_version_id"] for b in offers["bonds"]]
    for b in action["offer_set"]["bonds"]:
        assert b["wording"] and b["tier"] in ("supported", "exploratory") and "operator_fit" in b
        assert "no textual evidence span recorded" in b["evidence_note"]
    assert action["state_before"] == {"revision": 1, "encounter_count": 1, "count_for_version": 0, "active_version": offers["source_version"]}
    assert action["state_after"] == {"revision": 2, "encounter_count": 2, "count_for_version": 1, "active_version": bond["destination_version"]}
    third = encounters[2]["action"]
    assert third["offer_set"]["operator"] == "CONTRADICT" and third["bond_version_id"] == chosen["bond_version_id"]
    assert third["state_before"]["revision"] == 2 and third["state_after"]["revision"] == 3
    assert journey["rejections"] == []


def test_journey_marks_a_return_with_index_distance_and_intervening_count(isolated):
    """P1 -> X -> P1 (when the atlas offers the way back): the second P1 is a return."""
    session_id = _start("P1")["session_id"]
    offers = _options(session_id, "DEVELOP", policy="include-adjacent")
    result = _execute(session_id, offers, offers["bonds"][0], "r1")
    back = None
    for operator in ("ECHO", "DEVELOP", "CONTRADICT", "BRIDGE"):
        candidates = _options(session_id, operator, policy="include-adjacent")
        back = next((b for b in candidates["bonds"] if b["destination_page"] == "P1"), None)
        if back is not None:
            _execute(session_id, candidates, back, "r2")
            break
    if back is None:
        pytest.skip(f"the atlas offers no way back to P1 from {result['to_page']}")
    journey = Handlers.get_core_journey({"session_id": [session_id]})
    last = journey["encounters"][-1]
    assert last["is_return"] is True and last["previous_encounter_index"] == 0
    assert last["return_index_distance"] == 2 and last["intervening_encounters"] == 1
    assert last["action"]["state_before"]["count_for_version"] == 1 and last["action"]["state_after"]["count_for_version"] == 2


def test_journey_says_so_when_a_version_is_no_longer_current(isolated, monkeypatch):
    session_id, offers, bond, _ = _followed(isolated)
    changed = dict(FIELD.manifest)
    page = changed["P1"]
    changed["P1"] = type(page)(id=page.id, path=page.path, text=page.text + "\n\nAn added line.",
                               sha256=hashlib.sha256((page.text + "\n\nAn added line.").encode()).hexdigest(), order=page.order)
    fake = type(FIELD)(id=FIELD.id, label=FIELD.label, manifest=changed)
    monkeypatch.setattr(reader_server, "_load_field", lambda _fid: fake)
    journey = Handlers.get_core_journey({"session_id": [session_id]})
    start = journey["encounters"][0]
    assert start["prose"]["current"] is False and start["prose"]["text"] is None
    assert "no longer the current text of P1" in start["prose"]["note"]
    assert journey["encounters"][1]["prose"]["current"] is True


def test_journey_of_an_unknown_or_invalid_session(isolated):
    with pytest.raises(ApiError) as e:
        Handlers.get_core_journey({"session_id": ["s_never000"]})
    assert e.value.status == 404
    with pytest.raises(ApiError) as e2:
        Handlers.get_core_journey({"session_id": ["../etc"]})
    assert e2.value.status == 400


def test_crash_between_commit_and_projection_keeps_the_encounter_and_a_later_run_repairs_the_mirrors(isolated, monkeypatch):
    session_id = _start("P1")["session_id"]
    offers = _options(session_id)
    bond = offers["bonds"][0]

    def exploding(*_a, **_k):
        raise RuntimeError("simulated crash after the journal write")

    real_core = reader_server._core
    monkeypatch.setattr(reader_server, "_core", lambda field=None: Core(
        core_dir=isolated / "core", field=real_core(field).field, projectors=[exploding],
        options_provider=lambda f, p, o, policy: reader_server.OPTIONS_PROVIDER(f, p, o, policy=policy, mode="live")))
    result = _execute(session_id, offers, bond, "req-crash")
    assert result["status"] == "committed" and result["projection_errors"] == ["RuntimeError: simulated crash after the journal write"]
    monkeypatch.setattr(reader_server, "_core", real_core)

    # the commit stands: session and journey show the encounter although no mirror was written
    view = Handlers.get_core_session({"session_id": [session_id]})
    assert view["encounter_count"] == 2 and view["active_page"] == bond["destination_page"]
    journey = Handlers.get_core_journey({"session_id": [session_id]})
    assert journey["encounter_count"] == 2 and journey["encounters"][1]["action"]["request_id"] == "req-crash"
    assert not (isolated / "data" / "bonds.json").exists()
    assert [e["event"] for e in _log(isolated)] == ["page_viewed"]

    # repair: re-run the projector over the journal -- once, and then again
    projector = projectors.mirror_to_legacy_stores(isolated / "data", isolated / "session_log.jsonl", field=FIELD)
    projectors.rebuild(session_id, _journal(isolated, session_id), projector)
    assert list(_bonds(isolated)) == [bond["bond_version_id"]]
    assert len(_reader_state(isolated)["history"]) == 1
    assert [e["event"] for e in _log(isolated)] == ["page_viewed", "operator_proposed", "offer_accepted",
                                                    "accept_and_follow", "q_traversal", "page_viewed"]
    repaired = _snapshot(isolated)
    projectors.rebuild(session_id, _journal(isolated, session_id), projector)
    assert _snapshot(isolated) == repaired
    # a retry of the same click after the repair is still one recorded duplicate
    assert _execute(session_id, offers, bond, "req-crash")["duplicate"] is True
    assert _snapshot(isolated) == repaired


def test_partial_mirror_is_completed_without_duplicating_what_exists(isolated):
    """A crash after some session-log lines: the rerun adds only the missing lines."""
    session_id, offers, bond, _ = _followed(isolated)
    log_path = isolated / "session_log.jsonl"
    lines = log_path.read_text().splitlines()
    log_path.write_text("\n".join(lines[:3]) + "\n")  # keep page_viewed(start), operator_proposed, offer_accepted
    session_log._LINE_COUNTS.clear()
    reader = isolated / "data" / "reader_state.json"
    reader.unlink()  # and the history marker never got written
    projector = projectors.mirror_to_legacy_stores(isolated / "data", isolated / "session_log.jsonl", field=FIELD)
    projectors.rebuild(session_id, _journal(isolated, session_id), projector)
    assert [e["event"] for e in _log(isolated)] == ["page_viewed", "operator_proposed", "offer_accepted",
                                                    "accept_and_follow", "q_traversal", "page_viewed"]
    assert len(_reader_state(isolated)["history"]) == 1
    assert list(_bonds(isolated)) == [bond["bond_version_id"]]


# --- HTTP surface ------------------------------------------------------------------------

@pytest.fixture
def httpd():
    server = reader_server.ThreadingHTTPServer(("127.0.0.1", 0), reader_server.ReaderRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _http(url, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_http_roundtrip_error_shape_and_journey_page(httpd):
    status, session = _http(httpd + "/api/core/session", {"page": "P4"})
    assert status == 200 and session["active_page"] == "P4"
    sid = session["session_id"]
    status, offers = _http(httpd + "/api/core/options", {"session_id": sid, "operator": "ECHO", "policy": "discovery"})
    assert status == 200 and offers["bonds"]
    body = {"session_id": sid, "offer_set_id": offers["offer_set_id"], "bond_version_id": offers["bonds"][0]["bond_version_id"],
            "expected_revision": 42, "request_id": "http-1"}
    status, refused = _http(httpd + "/api/core/execute", body)
    assert status == 409
    assert refused["code"] == "stale_revision" and refused["reason"] and "error" in refused and isinstance(refused["details"], dict)
    assert refused["details"]["current_revision"] == 1
    status, done = _http(httpd + "/api/core/execute", {**body, "expected_revision": 1, "request_id": "http-2"})
    assert status == 200 and done["duplicate"] is False
    status, again = _http(httpd + "/api/core/execute", {**body, "expected_revision": 1, "request_id": "http-2"})
    assert status == 200 and again["duplicate"] is True
    status, st = _http(httpd + f"/api/core/status?session_id={sid}&request_id=http-1")
    assert status == 200 and st["status"] == "rejected" and st["code"] == "stale_revision"
    status, journey = _http(httpd + f"/api/core/journey?session_id={sid}")
    assert status == 200 and journey["encounter_count"] == 2 and len(journey["rejections"]) == 1
    for path in ("/journey", "/inspect/journey", f"/journey?session_id={sid}"):
        with urllib.request.urlopen(httpd + path, timeout=5) as r:
            assert r.status == 200 and b"Journey inspection" in r.read()
    with urllib.request.urlopen(httpd + "/journey.js", timeout=5) as r:
        assert r.status == 200


def test_journey_page_never_posts():
    js = (STATIC / "journey.js").read_text()
    html = (STATIC / "journey.html").read_text()
    code = "\n".join(line for line in js.splitlines() if not line.strip().startswith("//"))
    assert "POST" not in code and "method: \"GET\"" in code
    assert "/api/core/journey" in js and "/api/build" in js
    assert js.count("fetch(") == 1  # one fetch helper, GET only
    assert "textContent" in js and "innerHTML" not in js and "innerHTML" not in html
    assert "decision evidence (model distribution)" in js and "no textual evidence span recorded" in html
    assert 'data-testid="journey-status"' in html


def test_reader_buttons_use_the_core_endpoints():
    app = (STATIC / "app.js").read_text()
    assert '"/api/core/options"' in app and '"/api/core/execute"' in app and '"/api/core/session"' in app
    assert '"/api/follow-option"' not in app  # the buttons no longer follow through the legacy endpoint
    assert 'testid = "option-wording"' in app
    assert 'data-testid="core-session"' in (STATIC / "index.html").read_text()
    assert "/api/follow-option" in reader_server.POST_ROUTES and "/api/operator-options" in reader_server.GET_ROUTES
