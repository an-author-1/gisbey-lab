import json

import pytest

from gibsey_lab.memory import packet as pk
from test_memory_helpers import ev, make_field


def legacy_log():
    """Shaped like the real pre-milestone log: no seq, no hash, from_page null, the first
    views without `via`, operator results interleaved."""
    return [
        ev("field_selected"),
        ev("page_viewed", "PR4", from_page=None),
        ev("page_viewed", "PR1", from_page=None),
        ev("operator_result", source="PR1", operator="DEVELOP", kind="new", destination="PR2"),
        ev("accept_and_follow", source="PR1", operator="DEVELOP", destination="PR2", bond_id="b1"),
        ev("page_viewed", "PR2", from_page=None),                       # legacy: no via at all
        ev("operator_result", source="PR2", operator="BRIDGE", kind="new", destination="PR1"),
        ev("page_viewed", "PR2", from_page=None, via="dropdown"),       # reload: consecutive duplicate
        ev("page_viewed", "PR3", from_page=None, via="prev_next"),
        ev("back", "PR2", from_page=None, via="back"),
    ]


def test_exact_assembly_from_legacy_events():
    field = make_field()
    trace = pk.encounters_from_events(legacy_log(), field)
    assert [(e["seq"], e["page_id"], e["arrived_via"], e["operator"], e["revisit"]) for e in trace] == [
        (1, "PR4", "unknown", None, False),
        (2, "PR1", "unknown", None, False),
        (5, "PR2", "traversal", "DEVELOP", False),
        (8, "PR3", "next", None, False),
        (9, "PR2", "back", None, True),
    ]
    assert all(e["version_source"] == "current_manifest" and e["text_available"] for e in trace)
    assert trace[2]["text"] == field.manifest["PR2"].text and trace[2]["sha256"] == field.manifest["PR2"].sha256


def test_packet_excludes_current_and_records_arrival():
    field = make_field()
    packet = pk.build_memory_packet(field, "PR2", legacy_log(), candidate_policy="discovery", intention="  the mirror  ")
    assert packet["schema"] == "memory-packet/1" and packet["policy_version"] == "memory-v2" == pk.MEMORY_POLICY_VERSION
    assert packet["source"] == "session_log" and packet["field"] == "full-41" and packet["candidate_policy"] == "discovery"
    assert [e["page_id"] for e in packet["encounters"]] == ["PR4", "PR1", "PR2", "PR3"]
    assert packet["current"] == {"page_id": "PR2", "sha256": field.manifest["PR2"].sha256, "arrived_via": "back",
                                 "operator": None, "seq": 9, "revisit": True}
    assert packet["omitted_earlier_encounters"] == 0 and packet["intention"] == "the mirror"
    assert packet["trace_ref"]["first_seq"] == 1 and packet["trace_ref"]["last_seq"] == 9
    assert packet["trace_ref"]["log_path"].endswith("session_log.jsonl")


def test_back_adds_an_encounter_and_erases_nothing():
    field = make_field()
    events = [ev("page_viewed", "PR1", via="dropdown"), ev("page_viewed", "PR2", via="prev_next"),
              ev("page_viewed", "PR3", via="prev_next")]
    before = pk.encounters_from_events(events, field)
    after = pk.encounters_from_events(events + [ev("back", "PR2", via="back")], field)
    assert after[: len(before)] == before and len(after) == len(before) + 1
    assert after[-1]["arrived_via"] == "back" and after[-1]["revisit"] is True
    assert after[1]["revisit"] is False  # the first encounter of PR2 is not rewritten


def test_returning_by_any_route_is_a_revisit_and_direction_is_resolved():
    field = make_field()
    events = [ev("page_viewed", "PR2", via="dropdown"), ev("page_viewed", "PR1", via="prev_next"),
              ev("page_viewed", "LF3", via="dropdown"), ev("page_viewed", "PR2", via="dropdown")]
    trace = pk.encounters_from_events(events, field)
    assert [e["arrived_via"] for e in trace] == ["list", "previous", "list", "list"]
    assert [e["revisit"] for e in trace] == [False, False, False, True]


def test_new_style_events_use_seq_hash_and_q_traversal():
    field = make_field()
    events = [
        ev("page_viewed", "PR1", via="dropdown", seq=40, page_sha256=field.manifest["PR1"].sha256),
        ev("offer_proposed", source="PR1"), ev("offer_accepted", source="PR1"),
        ev("q_traversal", source="PR1", destination="LF2", operator="contradict", proposal_kind="operator", seq=43),
        ev("page_viewed", "LF2", via="traversal", seq=44, page_sha256=field.manifest["LF2"].sha256),
        ev("q_traversal", source="LF2", destination="P1", seq=45),
        ev("page_viewed", "P1", via="traversal", seq=46, page_sha256=field.manifest["P1"].sha256),
    ]
    trace = pk.encounters_from_events(events, field)
    assert [(e["seq"], e["version_source"], e["operator"]) for e in trace] == [
        (40, "event", None), (44, "event", "CONTRADICT"), (46, "event", None)]
    visible = pk.model_visible_state(pk.build_memory_packet(field, "P1", events, candidate_policy="discovery"))
    assert [e["arrived_by"] for e in visible["encounters"]] == ["picked from list", "followed a CONTRADICT operator selection"]
    assert visible["current_page_arrived_by"] == "followed an offered route"


def test_operator_selection_and_hand_follow_are_labeled_differently():
    field = make_field()
    events = [
        ev("page_viewed", "PR1", via="dropdown"),
        ev("accept_and_follow", source="PR1", operator="BRIDGE", destination="PR4"),   # legacy: always an operator
        ev("page_viewed", "PR4", via="traversal"),
        ev("accept_and_follow", source="PR4", operator="ECHO", destination="LF2", proposal_kind="operator"),
        ev("q_traversal", source="PR4", operator="ECHO", destination="LF2", proposal_kind="operator"),
        ev("page_viewed", "LF2", via="traversal", proposal_kind="operator"),
        # a hand follow whose single relation label happens to name an operator
        ev("accept_and_follow", source="LF2", operator="CONTRADICT", destination="P1", proposal_kind="offer"),
        ev("q_traversal", source="LF2", operator="CONTRADICT", destination="P1", proposal_kind="offer"),
        ev("page_viewed", "P1", via="traversal", proposal_kind="offer"),
        ev("page_viewed", "P2", via="prev_next"),
    ]
    trace = pk.encounters_from_events(events, field)
    assert [(e["page_id"], e["arrived_via"], e["operator"]) for e in trace] == [
        ("PR1", "list", None), ("PR4", "traversal", "BRIDGE"), ("LF2", "traversal", "ECHO"),
        ("P1", "offer", "CONTRADICT"), ("P2", "next", None)]
    visible = pk.model_visible_state(pk.build_memory_packet(field, "P2", events, candidate_policy="discovery"))
    assert [e["arrived_by"] for e in visible["encounters"]] == [
        "picked from list", "followed a BRIDGE operator selection", "followed an ECHO operator selection",
        "followed an offered route"]
    assert " offer\"" not in json.dumps(visible)  # the memory-v1 wording is gone


def test_fixture_model_visible_state_is_textually_independent_of_the_label_change():
    field = make_field()
    for path in (["PR1", "PR3", "PR2"], ["LF3", "PR2"], ["PR2"]):
        visible = pk.model_visible_state(pk.fixture_packet(field, path, candidate_policy="discovery"))
        labels = [e["arrived_by"] for e in visible["encounters"]] + [visible["current_page_arrived_by"]]
        assert set(labels) == {"arrival not specified"}
        assert "operator selection" not in json.dumps(visible) and "memory-v" not in json.dumps(visible)


def test_operator_of_an_unrelated_traversal_is_not_attached():
    field = make_field()
    events = [ev("page_viewed", "PR1", via="dropdown"),
              ev("accept_and_follow", source="PR1", operator="ECHO", destination="PR5"),
              ev("page_viewed", "PR6", via="traversal")]
    assert pk.encounters_from_events(events, field)[-1]["operator"] is None


def test_window_of_six_with_omitted_count():
    field = make_field()
    ids = ["PR1", "PR2", "PR3", "PR4", "PR5", "PR6", "PR7", "PR8", "LF1", "LF2"]
    events = [ev("page_viewed", pid, via="dropdown") for pid in ids]
    packet = pk.build_memory_packet(field, "LF2", events, candidate_policy="discovery")
    assert packet["window"] == 6 == pk.WINDOW
    assert [e["page_id"] for e in packet["encounters"]] == ["PR4", "PR5", "PR6", "PR7", "PR8", "LF1"]
    assert packet["omitted_earlier_encounters"] == 3 and packet["total_earlier_encounters"] == 9
    visible = pk.model_visible_state(packet)
    assert visible["omitted_earlier_encounters"] == 3 and "3 earlier encounter" in visible["note"]
    assert len(visible["encounters"]) == 6


def test_hash_mismatch_keeps_encounter_without_current_text():
    field = make_field()
    events = [ev("page_viewed", "PR1", via="dropdown", page_sha256="0" * 64), ev("page_viewed", "PR2", via="prev_next")]
    packet = pk.build_memory_packet(field, "PR2", events, candidate_policy="discovery")
    (encounter,) = packet["encounters"]
    assert encounter["version_source"] == "event_hash_mismatch" and encounter["text_available"] is False
    assert encounter["text"] is None and encounter["sha256"] == "0" * 64
    visible = pk.model_visible_state(packet)
    assert visible["encounters"][0]["text"] is None and "not available" in visible["encounters"][0]["note"]
    assert field.manifest["PR1"].text not in json.dumps(visible)


def test_model_visible_state_has_no_ids_hashes_or_notes():
    field = make_field()
    events = legacy_log() + [ev("preserved", bond_id="b1", note="HUMAN NOTE"), ev("review", reviewer_text="REVIEWER")]
    packet = pk.build_memory_packet(field, "PR2", events, candidate_policy="discovery", intention="why mirrors?")
    blob = json.dumps(pk.model_visible_state(packet))
    for pid in field.manifest:
        assert f'"{pid}"' not in blob and f"{pid} " not in blob
    for page in field.manifest.values():
        assert page.sha256 not in blob
    for forbidden in ("HUMAN NOTE", "REVIEWER", "page_id", "sha256", "seq", "liked", "agree", "b1"):
        assert forbidden not in blob
    visible = pk.model_visible_state(packet)
    assert visible["reader_stated_intention"] == "why mirrors?"
    assert set(visible) == {"encounters", "omitted_earlier_encounters", "note", "current_page_arrived_by",
                            "reader_stated_intention"}
    assert [e["text"] for e in visible["encounters"]] == [field.manifest[p].text for p in ("PR4", "PR1", "PR2", "PR3")]


def test_memory_sha_tracks_only_model_visible_content():
    field = make_field()
    a = pk.fixture_packet(field, ["PR1", "PR3", "PR2"], candidate_policy="discovery")
    b = pk.fixture_packet(field, ["LF3", "PR2"], candidate_policy="discovery")
    c = pk.fixture_packet(field, ["PR2"], candidate_policy="discovery")
    assert len({pk.memory_sha256(a), pk.memory_sha256(b), pk.memory_sha256(c)}) == 3
    assert pk.memory_sha256(a) == pk.memory_sha256(pk.fixture_packet(field, ["PR1", "PR3", "PR2"], candidate_policy="discovery"))
    relabeled = {**a, "trace_ref": {"log_path": "elsewhere"}}
    assert pk.memory_sha256(relabeled) == pk.memory_sha256(a)
    assert pk.memory_sha256({**a, "intention": "x"}) != pk.memory_sha256(a)


def test_fixture_packet_is_labeled_and_empty_history_is_well_formed():
    field = make_field()
    a = pk.fixture_packet(field, ["PR1", "PR3", "PR2"], candidate_policy="discovery")
    assert a["source"] == "demonstration_fixture" and a["current"]["page_id"] == "PR2"
    assert [e["page_id"] for e in a["encounters"]] == ["PR1", "PR3"] and a["trace_ref"]["log_path"] is None
    c = pk.model_visible_state(pk.fixture_packet(field, ["PR2"], candidate_policy="discovery"))
    assert c["encounters"] == [] and c["omitted_earlier_encounters"] == 0 and c["note"] == pk.NO_HISTORY_NOTE
    with pytest.raises(pk.PacketError):
        pk.fixture_packet(field, ["NOPE", "PR2"], candidate_policy="discovery")


def test_other_field_events_and_non_encounters_are_ignored():
    field = make_field()
    events = [ev("page_viewed", "PR1", via="dropdown"), {**ev("page_viewed", "PR5", via="dropdown"), "field": "holdout-21"},
              ev("field_selected"), ev("operator_result", source="PR1", destination="PR7"),
              ev("page_viewed", "PR2", via="prev_next")]
    assert [e["page_id"] for e in pk.encounters_from_events(events, field)] == ["PR1", "PR2"]
