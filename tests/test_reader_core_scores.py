import hashlib
from dataclasses import replace

import pytest

from gibsey_lab.core import fixtures, journal
from gibsey_lab.reader import server
from gibsey_lab.reader.server import ApiError, Handlers


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name, value in (("DATA_DIR", tmp_path / "data"), ("CORE_DIR", tmp_path / "core"),
                        ("SESSION_LOG_PATH", tmp_path / "legacy.jsonl"), ("RUNS_DIR", tmp_path / "runs")):
        monkeypatch.setattr(server, name, value)
    return tmp_path


def options(session):
    return Handlers.post_core_options({"session_id": session["session_id"], "operator": "ECHO"})


def follow(session, destination, request):
    offer = options(session)
    bond = next(bond for bond in offer["bonds"] if bond["destination_page"] == destination)
    result = Handlers.post_core_execute({
        "session_id": session["session_id"], "offer_set_id": offer["offer_set_id"],
        "bond_version_id": bond["bond_version_id"], "expected_revision": offer["revision"], "request_id": request,
    })
    return result["session"]


def test_demo_completes_and_inspection_retains_rules_without_legacy_writes(isolated):
    session = Handlers.post_core_demo({"mode": "recurrence"})
    assert session["synthetic"] and session["score"]["movement"] == "outward"
    session = follow(session, "RX3", "outward-one")
    excluded = [decision for decision in options(session)["decisions"] if not decision["allowed"]]
    assert any(decision["destination_page"] == "RX1" and decision["encounter_refs"] for decision in excluded)
    session = follow(session, "RX5", "outward-two")
    assert session["score"]["movement"] == "return"
    session = follow(session, "RX1", "return")
    assert session["score"]["status"] == "complete"
    journey = Handlers.get_core_journey({"session_id": [session["session_id"]]})
    assert journey["encounters"][-1]["intervening_encounters"] == 2
    assert journey["encounters"][-1]["score_after"]["status"] == "complete"
    assert journey["offer_sets"][1]["decisions"]
    assert not (isolated / "legacy.jsonl").exists()
    assert not (isolated / "data").exists()


def test_neutral_fixture_allows_early_return_and_relocation(isolated):
    session = Handlers.post_core_demo({"mode": "neutral"})
    session = follow(session, "RX3", "out")
    assert "RX1" in [bond["destination_page"] for bond in options(session)["bonds"]]
    moved = Handlers.post_core_relocate({"session_id": session["session_id"], "page": "RX1",
                                       "expected_revision": session["revision"], "request_id": "manual", "cause": "page_list"})
    assert moved["session"]["encounter_count"] == 3
    assert moved["session"]["score"]["counter"] == session["score"]["counter"]


@pytest.mark.parametrize("cause", ["previous", "next", "page_list", "back", "history_back", "history_forward", "other"])
def test_recurrence_manual_navigation_is_rejected_before_arrival(cause):
    session = Handlers.post_core_demo({"mode": "recurrence"})
    with pytest.raises(ApiError) as refusal:
        Handlers.post_core_relocate({"session_id": session["session_id"], "page": "RX5", "expected_revision": 1,
                                    "request_id": cause, "cause": cause})
    assert refusal.value.status == 409
    resumed = Handlers.get_core_session({"session_id": [session["session_id"]]})
    assert resumed["encounter_count"] == 1 and resumed["score"]["counter"] == 0


@pytest.mark.parametrize("handler", [Handlers.post_follow, Handlers.post_follow_offer,
                                     Handlers.post_follow_option, Handlers.post_accept_and_follow,
                                     Handlers.post_request_selection, Handlers.post_offers,
                                     Handlers.post_refine_options])
def test_legacy_research_is_unavailable_before_any_mutation(handler, isolated):
    session = Handlers.post_core_demo({"mode": "recurrence"})
    for body in ({"session_id": session["session_id"]}, {"field": fixtures.FIELD_ID}, {"from_page": "RX3"}):
        with pytest.raises(ApiError) as refusal:
            handler(body)
        assert refusal.value.status == 409
    assert len(journal.read_events(session["session_id"], isolated / "core")) == 1
    assert not (isolated / "legacy.jsonl").exists()


def test_demo_resume_and_exit_are_explicit():
    session = Handlers.post_core_demo({"mode": "recurrence"})
    session = follow(session, "RX3", "first")
    server._STATE_CACHE = server._StateCache()
    resumed = Handlers.post_core_session({"session_id": session["session_id"], "field": "full-41"})
    assert resumed["field"] == fixtures.FIELD_ID and resumed["score"] == session["score"]
    with pytest.raises(ApiError):
        Handlers.post_core_session({"session_id": session["session_id"], "new": True})
    ended = Handlers.post_core_lifecycle({"session_id": session["session_id"], "expected_revision": session["revision"],
                                        "request_id": "leave", "action": "exit"})
    assert ended["score"]["status"] == "exited" and ended["encounter_count"] == 2
    assert Handlers.get_pages({"field": [fixtures.FIELD_ID]})["groups"][0]["pages"] == ["RX1", "RX3", "RX5", "RX7"]


def test_offer_response_reports_blockage_and_recovery_at_the_same_revision():
    session = Handlers.post_core_demo({"mode": "recurrence"})
    blocked = Handlers.post_core_options({"session_id": session["session_id"], "operator": "CONTRADICT"})
    assert blocked["score"]["status"] == "blocked"
    assert blocked["current_revision"] == session["revision"]
    assert blocked["score"]["counter"] == 0
    recovered = options(session)
    assert recovered["score"]["status"] == "active"
    assert recovered["current_revision"] == blocked["current_revision"]
    assert recovered["score"]["counter"] == 0


@pytest.mark.parametrize("handler", [Handlers.get_operator_options, Handlers.get_saved_result])
def test_legacy_gets_cannot_write_synthetic_research_records(handler, isolated):
    session = Handlers.post_core_demo({"mode": "recurrence"})
    with pytest.raises(ApiError) as refusal:
        handler({"session_id": [session["session_id"]], "field": [fixtures.FIELD_ID], "page": ["RX1"], "operator": ["ECHO"]})
    assert refusal.value.status == 409
    assert not (isolated / "legacy.jsonl").exists()


def test_reader_and_journey_retain_destination_text_added_after_start(monkeypatch):
    session = Handlers.post_core_demo({"mode": "neutral"})
    field = fixtures.demo_field()
    recorded_text = "A changed synthetic garden.\n\nThis version first arrived after the session started."
    field.manifest["RX3"] = replace(field.manifest["RX3"], text=recorded_text,
                                    sha256=hashlib.sha256(recorded_text.encode()).hexdigest())
    monkeypatch.setattr(server, "_load_field", lambda _field: field)
    moved = Handlers.post_core_relocate({"session_id": session["session_id"], "page": "RX3",
                                       "expected_revision": session["revision"], "request_id": "new-text", "cause": "page_list"})
    new_text = recorded_text + "\n\nA later edit."
    field.manifest["RX3"] = replace(field.manifest["RX3"], text=new_text,
                                    sha256=hashlib.sha256(new_text.encode()).hexdigest())
    page = Handlers.get_page({"session_id": [session["session_id"]], "field": [fixtures.FIELD_ID], "id": ["RX3"]})
    assert page["text"] == recorded_text
    journey = Handlers.get_core_journey({"session_id": [session["session_id"]]})
    assert journey["encounters"][-1]["prose"]["text"] == recorded_text
    assert journey["encounters"][-1]["prose"]["current"] is False
    assert journey["encounters"][-1]["version_id"] == moved["to_version"]
