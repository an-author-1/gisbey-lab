import json

import pytest

from gibsey_lab.memory import contextual, packet as pk
from gibsey_lab.scoring import mock_dispatch
from test_memory_helpers import FAKE_MODEL, ScriptedDispatch, make_field


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "contextual" / "assessments.jsonl"
    monkeypatch.setattr(contextual, "ASSESSMENTS_PATH", path)
    return path


def _assess(field, packet, dispatch, candidate="LF2", **kw):
    kw.setdefault("mode", "mock")
    kw.setdefault("requested_model", "jev-test")
    kw.setdefault("atlas_config_id", "cfg-mock")
    return contextual.assess(packet, current_page=field.manifest["PR2"], candidate_page=field.manifest[candidate],
                             dispatch=dispatch, **kw)


def test_rubric_shape_and_explicit_role_keys():
    assert contextual.CONTEXTUAL_RUBRIC_VERSION == "contextual-rubric-v1"
    assert tuple(q.qid for q in contextual.QUESTIONS) == (
        "works_after_history", "grounded_reading_effect", "repeats_recent_reading")
    for q in contextual.QUESTIONS:
        assert len(q.levels) == 4
        for key in ("`reading_history`", "`current_page`", "`candidate_destination`", "FROM `current_page` TO"):
            assert key in q.instructions
        assert "empty" in q.instructions  # the no-history case is stated inside the ordinary prompt


def test_history_text_reaches_the_provider_request(store):
    field = make_field()
    packet = pk.fixture_packet(field, ["PR1", "PR3", "PR2"], candidate_policy="discovery")
    dispatch = ScriptedDispatch()
    record = _assess(field, packet, dispatch)
    (request,) = dispatch.requests
    assert request.kind == "contextual" and set(request.state) == {"reading_history", "current_page", "candidate_destination"}
    assert request.state["reading_history"] == pk.model_visible_state(packet)
    assert [e["text"] for e in request.state["reading_history"]["encounters"]] == [
        field.manifest["PR1"].text, field.manifest["PR3"].text]
    assert request.state["current_page"]["text"] == field.manifest["PR2"].text
    assert request.state["candidate_destination"]["text"] == field.manifest["LF2"].text
    blob = json.dumps(request.canonical())
    assert not any(f'"{pid}"' in blob for pid in field.manifest) and field.manifest["LF2"].sha256 not in blob
    # the stored record holds exactly what was sent
    (stored,) = contextual.read_records()
    assert stored["state"] == request.state and stored["request_sha256"] == request.request_sha256()
    assert stored["questions"] == [q.to_dict() for q in contextual.QUESTIONS]
    assert stored["schema"] == "contextual-assessment/1" and stored["layer"] == "history_conditioned"
    assert stored["memory_sha256"] == pk.memory_sha256(packet) == record["memory_sha256"]
    assert stored["mode"] == "mock" and stored["returned_model"] == FAKE_MODEL and stored["candidate_id"] == "LF2"
    assert stored["usage"] == {"input_tokens": 100, "output_tokens": 10} and "from_cache" not in stored


def test_no_history_is_the_same_well_formed_request(store):
    field = make_field()
    with_history = contextual.build_contextual_request(
        pk.fixture_packet(field, ["LF3", "PR2"], candidate_policy="discovery"), "cur", "cand", "m")
    without = contextual.build_contextual_request(
        pk.fixture_packet(field, ["PR2"], candidate_policy="discovery"), "cur", "cand", "m")
    assert without.questions == with_history.questions and set(without.state) == set(with_history.state)
    assert without.state["reading_history"]["encounters"] == []
    assert without.request_sha256() != with_history.request_sha256()
    assert mock_dispatch(without).status == "ok"


def test_cache_key_changes_with_every_component():
    base = dict(current_sha256="c", candidate_sha256="d", memory_sha256="m", requested_model="jev",
                pinned_returned_model="jev-1", atlas_config_id="cfg", memory_policy_version="memory-v1",
                contextual_rubric_version="contextual-rubric-v1")
    key = contextual.cache_key(**base)
    assert key == contextual.cache_key(**base)
    for name in base:
        assert contextual.cache_key(**{**base, name: base[name] + "-changed"}) != key, name


def test_cached_result_is_labeled_and_needs_exact_memory(store):
    field = make_field()
    a = pk.fixture_packet(field, ["PR1", "PR3", "PR2"], candidate_policy="discovery")
    b = pk.fixture_packet(field, ["LF3", "PR2"], candidate_policy="discovery")
    dispatch = ScriptedDispatch()
    first = _assess(field, a, dispatch)
    again = _assess(field, a, dispatch)
    assert first["from_cache"] is False and again["from_cache"] is True
    assert again["assessment_id"] == first["assessment_id"] and len(dispatch.requests) == 1

    assert _assess(field, b, dispatch)["from_cache"] is False           # different memory
    assert _assess(field, a, dispatch, candidate="LF4")["from_cache"] is False  # different endpoint
    assert _assess(field, a, dispatch, requested_model="other")["from_cache"] is False
    assert _assess(field, a, dispatch, atlas_config_id="cfg-2")["from_cache"] is False
    assert _assess(field, a, dispatch, reuse_cache=False)["from_cache"] is False
    assert len(dispatch.requests) == 6 and len(contextual.read_records()) == 6  # append-only


def test_mock_record_is_never_reused_for_live(store):
    field = make_field()
    packet = pk.fixture_packet(field, ["PR2"], candidate_policy="discovery")
    _assess(field, packet, ScriptedDispatch(mode="mock"), mode="mock")
    live = ScriptedDispatch(mode="live")
    assert _assess(field, packet, live, mode="live")["from_cache"] is False and len(live.requests) == 1


def test_error_is_stored_and_never_reused(store):
    field = make_field()
    packet = pk.fixture_packet(field, ["PR2"], candidate_policy="discovery")
    failing = ScriptedDispatch(lambda request: "error")
    first = _assess(field, packet, failing)
    assert first["status"] == "error" and first["from_cache"] is False and first["answers"] == {}
    working = ScriptedDispatch()
    second = _assess(field, packet, working)
    assert second["status"] == "ok" and second["from_cache"] is False and len(working.requests) == 1
    assert [r["status"] for r in contextual.read_records()] == ["error", "ok"]

    def boom(request):
        raise RuntimeError("socket closed")

    raised = _assess(field, packet, boom, candidate="LF5")
    assert raised["status"] == "error" and "socket closed" in raised["errors"][0]


def test_dispatch_mode_mismatch_and_wrong_model_are_not_usable(store):
    field = make_field()
    packet = pk.fixture_packet(field, ["PR2"], candidate_policy="discovery")
    wrong_mode = _assess(field, packet, ScriptedDispatch(mode="mock"), mode="live")
    assert wrong_mode["status"] == "error" and wrong_mode["mode"] == "mock"
    wrong_model = _assess(field, packet, ScriptedDispatch(), pinned_returned_model="jev-1.13.0")
    assert wrong_model["status"] == "invalid"
    assert contextual.find_reusable(wrong_model["cache_key"], "mock", pinned_returned_model="jev-1.13.0") is None


def test_base_profile_is_never_returned_as_contextual(store):
    field = make_field()
    packet = pk.fixture_packet(field, ["PR2"], candidate_policy="discovery")
    key = contextual.cache_key(
        current_sha256=field.manifest["PR2"].sha256, candidate_sha256=field.manifest["LF2"].sha256,
        memory_sha256=pk.memory_sha256(packet), requested_model="jev-test", pinned_returned_model=None,
        atlas_config_id="cfg-mock")
    store.parent.mkdir(parents=True)
    impostors = [
        {"schema": "atlas-assessment/1", "cache_key": key, "mode": "mock", "status": "ok", "assessment_id": "atlas_x",
         "dimensions": {}},
        {"schema": "contextual-assessment/1", "layer": "base_pair_profile", "cache_key": key, "mode": "mock",
         "status": "ok", "assessment_id": "mislabeled"},
    ]
    store.write_text("".join(json.dumps(r) + "\n" for r in impostors))
    dispatch = ScriptedDispatch()
    record = _assess(field, packet, dispatch)
    assert record["from_cache"] is False and record["cache_key"] == key and len(dispatch.requests) == 1
    assert record["layer"] == "history_conditioned" and record["assessment_id"].startswith("ctx_")


def test_packet_for_another_page_version_is_refused(store):
    field = make_field()
    packet = pk.fixture_packet(field, ["PR2"], candidate_policy="discovery")
    packet["current"]["sha256"] = "f" * 64
    with pytest.raises(ValueError):
        _assess(field, packet, ScriptedDispatch())
