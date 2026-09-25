"""Core v0.3: identities, journal atomicity, pure reduction, and execute_action semantics.
Everything runs against a temp core dir with a synthetic field and a fake options
provider -- no atlas records, no provider, no reader server."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from gibsey_lab.core import identity, journal, reducer
from gibsey_lab.core.core import Core, CoreError
from gibsey_lab.fields import Field
from tests.conftest import make_page


def synthetic_field(tmp_path) -> Field:
    manifest = {}
    for i in range(1, 6):
        manifest[f"P{i}"] = make_page(f"P{i}", f"Page {i} opens here. It goes on about {i}.", i, tmp_path / f"P{i}.md")
    manifest["F1"] = make_page("F1", "A foreword sentence! Then more.", 1, tmp_path / "F1.md")
    return Field(id="full-41", label="synthetic", manifest=manifest)


def fake_options(field: Field, page_id: str, operator: str, policy: str) -> dict:
    """Every eligible page, strongest first by page order; the last one is 'exploratory'."""
    eligible = field.eligible_candidate_ids(page_id, policy)
    options = []
    for rank, dest in enumerate(eligible, start=1):
        options.append({
            "destination_id": dest, "destination_sha256": field.manifest[dest].sha256,
            "tier": "exploratory" if rank == len(eligible) else "supported",
            "tier_label": "Exploratory — weak or uncertain fit" if rank == len(eligible) else "Supported",
            "operator_fit": {"dimension": "development", "score": 2.5, "score_norm": 0.83, "confidence": 0.7,
                             "nearest_level": 2},
            "cautions": [], "assessment_id": f"as-{page_id}-{dest}-{operator}", "rank": rank, "rank_reasons": [],
        })
    return {"schema": "operator-options/1", "policy_version": "operator-options-v1", "state": "options",
            "options": options, "counts": {"eligible": len(eligible), "ineligible_policy": 0}, "unusable": [],
            "atlas_config_id": "cfg-test"}


@pytest.fixture
def core(tmp_path):
    return Core(core_dir=tmp_path / "core", field=synthetic_field(tmp_path / "vault"), options_provider=fake_options)


def first_bond(core: Core, session: str, operator: str = "DEVELOP") -> tuple[dict, dict]:
    offer = core.resolve_options(session, operator)
    return offer, offer["bonds"][0]


# ------------------------------------------------------------------ identities


def test_version_and_bond_ids_are_content_hashes():
    sha = "c" * 64
    assert identity.version_id("P1", sha) == "P1@" + "c" * 12
    assert identity.parse_version_id("PR5@0123456789ab") == ("PR5", "0123456789ab")
    with pytest.raises(ValueError):
        identity.version_id("p1", sha)
    a = identity.bond_version_id(source_version="P1@" + "a" * 12, destination_version="P2@" + "b" * 12,
                                 operator="ECHO", wording="Exact sentence.")
    same = identity.bond_version_id(source_version="P1@" + "a" * 12, destination_version="P2@" + "b" * 12,
                                    operator="ECHO", wording="Exact sentence.")
    reworded = identity.bond_version_id(source_version="P1@" + "a" * 12, destination_version="P2@" + "b" * 12,
                                        operator="ECHO", wording="Exact sentence")
    assert a == same and a != reworded
    with pytest.raises(ValueError):
        identity.bond_version_id(source_version="P1@" + "a" * 12, destination_version="P2@" + "b" * 12,
                                 operator="RETURN", wording="x")


# ------------------------------------------------------------------ journal


def test_journal_append_is_one_line_with_sequential_seq_and_heals_a_torn_tail(tmp_path):
    e0 = journal.append("s1", "session_started", {"version_id": "P1@" + "a" * 12, "page_id": "P1"},
                        revision_after=1, core_dir=tmp_path)
    assert e0["seq"] == 0
    path = journal.journal_path("s1", tmp_path)
    with open(path, "ab") as f:
        f.write(b'{"schema": "core-event/1", "seq": 1, "event": "presented", "torn":')  # crash mid-line
    with pytest.raises(journal.JournalError):
        journal.read_events("s1", tmp_path)
    # a torn tail is visible, never silently dropped; a healed file must be repaired explicitly
    lines = path.read_bytes().split(b"\n")
    path.write_bytes(b"\n".join(lines[:-1]) + b"\n")
    e1 = journal.append("s1", "presented", {"offer_set_id": "x"}, revision_after=1, core_dir=tmp_path)
    assert e1["seq"] == 1 and [e["seq"] for e in journal.read_events("s1", tmp_path)] == [0, 1]
    with pytest.raises(journal.JournalError):
        journal.append("s1", "presented", {}, revision_after=1, core_dir=tmp_path, expected_seq=1)


def test_journal_concurrent_appends_never_interleave(tmp_path):
    journal.append("s2", "session_started", {"version_id": "P1@" + "a" * 12, "page_id": "P1"}, revision_after=1,
                   core_dir=tmp_path)

    def worker(n):
        for _ in range(20):
            journal.append("s2", "presented", {"offer_set_id": f"o{n}"}, revision_after=1, core_dir=tmp_path)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    events = journal.read_events("s2", tmp_path)
    assert [e["seq"] for e in events] == list(range(81))


# ------------------------------------------------------------------ reducer


def test_reducer_is_pure_and_records_return_spacing():
    v1, v2 = "P1@" + "1" * 12, "P2@" + "2" * 12
    events = [
        {"seq": 0, "session_id": "s", "event": "session_started", "version_id": v1, "page_id": "P1", "revision_after": 1},
        {"seq": 1, "event": "offer_set_created", "offer_set_id": "o1", "revision": 1, "source_version": v1,
         "bond_version_ids": ["b1"], "revision_after": 1},
        {"seq": 2, "event": "action_committed", "request_id": "r1", "fingerprint": "f1", "offer_set_id": "o1",
         "bond_version_id": "b1", "from_version": v1, "to_version": v2, "to_page": "P2", "revision_after": 2},
        {"seq": 3, "event": "offer_set_created", "offer_set_id": "o2", "revision": 2, "source_version": v2,
         "bond_version_ids": ["b2"], "revision_after": 2},
        {"seq": 4, "event": "action_committed", "request_id": "r2", "fingerprint": "f2", "offer_set_id": "o2",
         "bond_version_id": "b2", "from_version": v2, "to_version": v1, "to_page": "P1", "revision_after": 3},
    ]
    before = json.dumps(events)
    state = reducer.reduce(events)
    assert json.dumps(events) == before  # inputs untouched
    assert state.r == 3 and state.v == v1 and [h["version_id"] for h in state.H] == [v1, v2, v1]
    assert state.c == {v1: 2, v2: 1} and state.ell == {v1: 2, v2: 1}
    back = state.H[2]
    assert back["previous_encounter_index"] == 0 and back["return_index_distance"] == 2 and back["intervening_encounters"] == 1
    assert state.offer_sets == {}  # o2 belonged to revision 2; after the move it is stale
    assert reducer.reduce(events).canonical() == state.canonical()  # deterministic
    with pytest.raises(reducer.ReduceError):
        reducer.reduce([events[0], dict(events[2], seq=1, revision_after=5)])  # declared revision disagrees
    bad = [events[0], dict(events[2], seq=1, from_version=v2)]
    with pytest.raises(reducer.ReduceError):
        reducer.reduce(bad)  # action from a version that is not active


def test_reordered_paths_stay_distinct_even_with_equal_counts():
    a, b, c = ("P1@" + "1" * 12, "P2@" + "2" * 12, "P3@" + "3" * 12)

    def path(*versions):
        events = [{"seq": 0, "session_id": "s", "event": "session_started", "version_id": versions[0],
                   "page_id": identity.page_of(versions[0]), "revision_after": 1}]
        for n, (src, dst) in enumerate(zip(versions, versions[1:]), start=1):
            events.append({"seq": len(events), "event": "action_committed", "request_id": f"r{n}", "fingerprint": "f",
                           "offer_set_id": "o", "bond_version_id": "b", "from_version": src, "to_version": dst,
                           "to_page": identity.page_of(dst), "revision_after": n + 1})
        return reducer.reduce(events)

    s1, s2 = path(a, b, c, a), path(a, c, b, a)
    assert s1.c == s2.c and s1.r == s2.r
    assert [h["version_id"] for h in s1.H] != [h["version_id"] for h in s2.H]
    assert s1.canonical() != s2.canonical()


# ------------------------------------------------------------------ execute_action


def test_resolve_twice_at_one_revision_is_one_offer_set_and_one_event(core):
    core.start_session("P1", session_id="sess1")
    first, second = core.resolve_options("sess1", "DEVELOP"), core.resolve_options("sess1", "DEVELOP")
    assert first["offer_set_id"] == second["offer_set_id"] and second["reused"] is True
    kinds = [e["event"] for e in journal.read_events("sess1", core.core_dir)]
    assert kinds == ["session_started", "offer_set_created"]
    assert [b["destination_page"] for b in first["bonds"]][:2] == ["F1", "P3"]  # P2 is P1's neighbor: excluded
    assert first["bonds"][1]["wording"] == "Page 3 opens here."
    assert first["bonds"][0]["wording_source"] == "destination_opening_sentence"


def test_commit_then_identical_retry_then_conflicting_reuse(core):
    core.start_session("P1", session_id="sess2")
    offer, bond = first_bond(core, "sess2")
    done = core.execute_action("sess2", offer_set_id=offer["offer_set_id"], bond_version_id=bond["bond_version_id"],
                               expected_revision=1, request_id="req-1")
    assert done["status"] == "committed" and done["revision_after"] == 2 and done["encounter_index"] == 1
    events_after = len(journal.read_events("sess2", core.core_dir))

    again = core.execute_action("sess2", offer_set_id=offer["offer_set_id"], bond_version_id=bond["bond_version_id"],
                                expected_revision=1, request_id="req-1")
    assert again["duplicate"] is True and again["to_page"] == done["to_page"]
    assert len(journal.read_events("sess2", core.core_dir)) == events_after  # dedup writes nothing
    assert len(core.state("sess2").H) == 2

    with pytest.raises(CoreError) as e:
        core.execute_action("sess2", offer_set_id=offer["offer_set_id"], bond_version_id=offer["bonds"][1]["bond_version_id"],
                            expected_revision=1, request_id="req-1")
    assert e.value.code == "request_id_reused"


def test_dedup_is_resolved_before_staleness(core):
    """The identical retry arrives after its own success changed the revision: it must be
    recognized as a duplicate, not rejected as stale."""
    core.start_session("P1", session_id="sess3")
    offer, bond = first_bond(core, "sess3")
    core.execute_action("sess3", offer_set_id=offer["offer_set_id"], bond_version_id=bond["bond_version_id"],
                        expected_revision=1, request_id="click")
    assert core.state("sess3").r == 2
    retry = core.execute_action("sess3", offer_set_id=offer["offer_set_id"], bond_version_id=bond["bond_version_id"],
                                expected_revision=1, request_id="click")
    assert retry["duplicate"] is True


def test_stale_tab_and_bad_inputs_are_rejected_journaled_and_move_nothing(core):
    core.start_session("P1", session_id="sess4")
    offer, bond = first_bond(core, "sess4")
    core.execute_action("sess4", offer_set_id=offer["offer_set_id"], bond_version_id=bond["bond_version_id"],
                        expected_revision=1, request_id="ok")
    before = core.state("sess4").canonical()
    for request_id, kwargs, code in [
        ("stale", dict(offer_set_id=offer["offer_set_id"], bond_version_id=offer["bonds"][1]["bond_version_id"], expected_revision=1), "stale_revision"),
        ("old-offer", dict(offer_set_id=offer["offer_set_id"], bond_version_id=offer["bonds"][1]["bond_version_id"], expected_revision=2), "unknown_or_stale_offer_set"),
    ]:
        with pytest.raises(CoreError) as e:
            core.execute_action("sess4", request_id=request_id, **kwargs)
        assert e.value.code == code
        status = core.get_action_status("sess4", request_id)
        assert status["status"] == "rejected" and status["code"] == code
    fresh, fresh_bond = first_bond(core, "sess4")
    with pytest.raises(CoreError) as e:
        core.execute_action("sess4", offer_set_id=fresh["offer_set_id"], bond_version_id="bond_not_offered",
                            expected_revision=2, request_id="not-offered")
    assert e.value.code == "not_offered"
    after = core.state("sess4").canonical()
    assert after["v"] == before["v"] and after["H"] == before["H"] and after["r"] == before["r"]
    # a retried rejection returns the recorded refusal, and a reused id with new inputs is a conflict
    with pytest.raises(CoreError) as e:
        core.execute_action("sess4", offer_set_id=offer["offer_set_id"], bond_version_id=offer["bonds"][1]["bond_version_id"],
                            expected_revision=1, request_id="stale")
    assert e.value.code == "stale_revision" and e.value.details.get("duplicate") is True
    with pytest.raises(CoreError) as e:
        core.execute_action("sess4", offer_set_id=fresh["offer_set_id"], bond_version_id=fresh_bond["bond_version_id"],
                            expected_revision=2, request_id="stale")
    assert e.value.code == "request_id_reused"


def test_destination_version_change_is_caught_at_execute_time(core, tmp_path):
    core.start_session("P1", session_id="sess5")
    offer, bond = first_bond(core, "sess5")
    dest = bond["destination_page"]
    edited = make_page(dest, "Edited text now.", core.field.manifest[dest].order, tmp_path / "x.md")
    core._field = Field(id="full-41", label="edited", manifest={**core.field.manifest, dest: edited})
    with pytest.raises(CoreError) as e:
        core.execute_action("sess5", offer_set_id=offer["offer_set_id"], bond_version_id=bond["bond_version_id"],
                            expected_revision=1, request_id="edited")
    assert e.value.code == "destination_version_changed"


def test_paused_session_rejects_navigation_and_resume_restores(core):
    core.start_session("P1", session_id="sess6")
    offer, bond = first_bond(core, "sess6")
    core.pause("sess6")
    with pytest.raises(CoreError) as e:
        core.execute_action("sess6", offer_set_id=offer["offer_set_id"], bond_version_id=bond["bond_version_id"],
                            expected_revision=2, request_id="while-paused")
    assert e.value.code == "paused"
    core.unpause("sess6")
    fresh, fresh_bond = first_bond(core, "sess6")
    done = core.execute_action("sess6", offer_set_id=fresh["offer_set_id"], bond_version_id=fresh_bond["bond_version_id"],
                               expected_revision=3, request_id="after-resume")
    assert done["status"] == "committed" and len(core.state("sess6").H) == 2  # pause/resume added no encounter


def test_state_survives_a_fresh_core_over_the_same_journal(core, tmp_path):
    core.start_session("P1", session_id="sess7")
    offer, bond = first_bond(core, "sess7")
    core.execute_action("sess7", offer_set_id=offer["offer_set_id"], bond_version_id=bond["bond_version_id"],
                        expected_revision=1, request_id="r")
    before = core.resume_session("sess7")
    restarted = Core(core_dir=core.core_dir, field=core.field, options_provider=fake_options)
    after = restarted.resume_session("sess7")
    assert after["state"] == before["state"] and after["encounters"] == before["encounters"]
    assert reducer.reduce_with_trace(journal.read_events("sess7", core.core_dir))[-1]["state"] == before["state"]


def test_projector_failure_never_uncommits_and_projectors_run_after_commit(tmp_path):
    calls = []

    def bad_projector(session_id, event, state):
        calls.append(event["event"])
        if event["event"] == "action_committed":
            raise RuntimeError("mirror store unavailable")

    core = Core(core_dir=tmp_path / "core", field=synthetic_field(tmp_path / "v"), options_provider=fake_options,
                projectors=[bad_projector])
    core.start_session("P1", session_id="sess8")
    offer, bond = first_bond(core, "sess8")
    done = core.execute_action("sess8", offer_set_id=offer["offer_set_id"], bond_version_id=bond["bond_version_id"],
                               expected_revision=1, request_id="r")
    assert done["status"] == "committed" and done["projection_errors"]
    assert core.state("sess8").v == bond["destination_version"]
    assert calls[-1] == "action_committed"


# ------------------------------------------------------------------ replay


def test_state_and_decision_replay_agree_and_detect_drift(core, tmp_path):
    from gibsey_lab.core import replay

    core.start_session("P1", session_id="sess9")
    offer, bond = first_bond(core, "sess9")
    core.execute_action("sess9", offer_set_id=offer["offer_set_id"], bond_version_id=bond["bond_version_id"],
                        expected_revision=1, request_id="r1")
    core.resolve_options("sess9", "ECHO")
    result = replay.replay("sess9", core)
    assert result["ok"] and result["provider_calls"] == 0 and result["decision_replay"]["offer_sets"] == 2
    bundle = replay.export_bundle("sess9", core, tmp_path / "bundle")
    data = json.loads(bundle.read_text())
    assert data["dspy_used"] is False and all(v["retained"] for v in data["versions"].values())
    assert len(data["versions"]) == 2 and data["replay"]["ok"]

    # ranking policy drift: the same page now yields a different order -> decision replay reports it
    core._options_provider = lambda f, p, o, policy: {**fake_options(f, p, o, policy),
                                                      "options": list(reversed(fake_options(f, p, o, policy)["options"]))}
    drifted = replay.decision_replay("sess9", core)
    assert not drifted["ok"] and len(drifted["drift"]) == 2


# ------------------------------------------------------------------ relocation (session 2)


def mixed_journey(core: Core, session: str = "mixed01") -> dict:
    """start P1 -> Q to first DEVELOP bond -> manual next -> manual back to P1 -> Q ECHO."""
    core.start_session("P1", session_id=session)
    offer, bond = first_bond(core, session)
    core.execute_action(session, offer_set_id=offer["offer_set_id"], bond_version_id=bond["bond_version_id"],
                        expected_revision=1, request_id="q1")
    core.relocate(session, page_id="P3", expected_revision=2, request_id="n1", cause="next")
    core.relocate(session, page_id="P1", expected_revision=3, request_id="b1", cause="back")
    offer2, bond2 = first_bond(core, session, "ECHO")
    core.execute_action(session, offer_set_id=offer2["offer_set_id"], bond_version_id=bond2["bond_version_id"],
                        expected_revision=4, request_id="q2")
    return {"offer": offer, "bond": bond, "offer2": offer2}


def test_relocation_keeps_one_session_with_distinct_provenance_and_return_spacing(core):
    mixed_journey(core)
    state = core.state("mixed01")
    assert [(h["page_id"], h["via"], h.get("cause"), h["bond_version_id"] is not None) for h in state.H] == [
        ("P1", "start", None, False), ("F1", "Q", None, True), ("P3", "manual", "next", False),
        ("P1", "manual", "back", False), ("F1", "Q", None, True)]
    back = state.H[3]
    assert back["return_index_distance"] == 3 and back["intervening_encounters"] == 2
    assert state.r == 5 and state.c["P1@" + core.field.manifest["P1"].sha256[:12]] == 2
    kinds = [e["event"] for e in journal.read_events("mixed01", core.core_dir)]
    assert kinds.count("relocation_committed") == 2 and kinds.count("action_committed") == 2
    relocation = next(e for e in journal.read_events("mixed01", core.core_dir) if e["event"] == "relocation_committed")
    assert relocation["operator"] is None and relocation["bond_version_id"] is None and relocation["offer_set_id"] is None


def test_relocation_dedup_reuse_stale_noop_and_offer_invalidation(core):
    core.start_session("P1", session_id="mixed02")
    offer, bond = first_bond(core, "mixed02")
    first = core.relocate("mixed02", page_id="P4", expected_revision=1, request_id="n1", cause="page_list")
    assert first["status"] == "committed" and first["revision_after"] == 2
    events_after = len(journal.read_events("mixed02", core.core_dir))
    again = core.relocate("mixed02", page_id="P4", expected_revision=1, request_id="n1", cause="page_list")
    assert again["duplicate"] is True and len(journal.read_events("mixed02", core.core_dir)) == events_after
    assert len(core.state("mixed02").H) == 2
    with pytest.raises(CoreError) as e:
        core.relocate("mixed02", page_id="P5", expected_revision=1, request_id="n1", cause="page_list")
    assert e.value.code == "request_id_reused"
    with pytest.raises(CoreError) as e:
        core.relocate("mixed02", page_id="P5", expected_revision=1, request_id="stale", cause="next")
    assert e.value.code == "stale_revision" and len(core.state("mixed02").H) == 2
    noop = core.relocate("mixed02", page_id="P4", expected_revision=2, request_id="same", cause="page_list")
    assert noop["status"] == "noop" and len(core.state("mixed02").H) == 2
    assert core.get_action_status("mixed02", "same")["status"] == "unknown"  # a no-op journals nothing
    with pytest.raises(CoreError) as e:  # the offer set made before the move is stale now
        core.execute_action("mixed02", offer_set_id=offer["offer_set_id"], bond_version_id=bond["bond_version_id"],
                            expected_revision=2, request_id="q-old")
    assert e.value.code == "unknown_or_stale_offer_set"
    with pytest.raises(CoreError) as e:
        core.relocate("mixed02", page_id="ZZ9", expected_revision=2, request_id="bad", cause="page_list")
    assert e.value.code == "unknown_page"
    with pytest.raises(CoreError) as e:
        core.relocate("mixed02", page_id="P5", expected_revision=2, request_id="c", cause="teleport")
    assert e.value.code == "unknown_cause"
    core.pause("mixed02")
    with pytest.raises(CoreError) as e:
        core.relocate("mixed02", page_id="P5", expected_revision=3, request_id="p", cause="next")
    assert e.value.code == "paused"


def test_replay_understands_relocations_and_invents_no_offer_set(core, tmp_path):
    from gibsey_lab.core import replay

    mixed_journey(core, "mixed03")
    result = replay.replay("mixed03", core)
    assert result["ok"] and result["decision_replay"]["offer_sets"] == 2  # the two Q offer sets only
    trace = reducer.reduce_with_trace(journal.read_events("mixed03", core.core_dir))
    assert [t["state"]["r"] for t in trace] == [1, 1, 2, 3, 4, 4, 5]
    bundle = json.loads(replay.export_bundle("mixed03", core, tmp_path / "b").read_text())
    assert len(bundle["versions"]) == 3 and bundle["replay"]["ok"]


def test_session_1_journal_without_relocations_still_reduces_identically():
    """A copy of a real session-1 journal (two offer sets, no action) is read-only fixture data."""
    real = Path(__file__).resolve().parents[1] / "data" / "core" / "sessions" / "s_d09a7820e595" / "events.jsonl"
    if not real.exists():
        pytest.skip("real session-1 journal not present")
    events = [json.loads(line) for line in real.read_text().splitlines() if line.strip()]
    state = reducer.reduce(events)
    assert [e["event"] for e in events] == ["session_started", "offer_set_created", "offer_set_created"]
    assert state.r == 1 and len(state.H) == 1 and state.page == "P1" and len(state.offer_sets) == 2


def test_pause_and_resume_make_earlier_offer_sets_stale(core):
    core.start_session("P1", session_id="mixed04")
    offer, bond = first_bond(core, "mixed04")
    core.pause("mixed04")
    core.unpause("mixed04")
    with pytest.raises(CoreError) as e:
        core.execute_action("mixed04", offer_set_id=offer["offer_set_id"], bond_version_id=bond["bond_version_id"],
                            expected_revision=3, request_id="after-pause")
    assert e.value.code == "unknown_or_stale_offer_set"
