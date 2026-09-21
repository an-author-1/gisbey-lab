"""The memory pipeline against the REAL atlas API (worker B's package), mock mode, with
every store redirected to tmp_path. Skipped when the atlas package is not importable."""
import pytest

from gibsey_lab.fields import load_field
from gibsey_lab.memory import contextual, demo, offers
from gibsey_lab.scoring import MOCK_MODEL, mock_dispatch
from test_memory_helpers import leveled_outcome

api = pytest.importorskip("gibsey_lab.atlas.api")
store = pytest.importorskip("gibsey_lab.atlas.store")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ASSESSMENTS_PATH", tmp_path / "atlas" / "assessments.jsonl")
    monkeypatch.setattr(api, "CONFIG_PATH", tmp_path / "atlas" / "active_config.json")
    monkeypatch.setattr(contextual, "ASSESSMENTS_PATH", tmp_path / "contextual" / "assessments.jsonl")
    monkeypatch.setattr(offers, "OFFER_SETS_PATH", tmp_path / "contextual" / "offer_sets.jsonl")
    monkeypatch.setattr(demo, "DEMO_DIR", tmp_path / "demos" / "pr2_memory")
    return tmp_path


def test_unbuilt_atlas_is_reported_as_incomplete_not_as_no_offers():
    field = load_field("full-41")
    result = offers.build_offers(field, "PR2", [], policy="discovery", dispatch=mock_dispatch, mode="mock",
                                 requested_model="jev-latest")
    assert result["state"] == "atlas_incomplete" and result["base_counts"]["unassessed"] == 40
    assert result["base_counts"]["eligible"] == 38 and result["not_assessed_count"] == 38


def test_mock_atlas_then_offers_and_demo_end_to_end(isolated):
    """Inputs are constructed so exactly one outcome is correct: only LF3 (development 3)
    and F5 (contradiction 2) clear a base relation floor, and only LF3 qualifies
    contextually. Everything runs through the real atlas build, store and API."""
    field = load_field("full-41")
    text_to_id = {page.text: pid for pid, page in field.manifest.items()}
    base_levels = {"LF3": {"development": 3}, "F5": {"contradiction": 2}}
    contextual_levels = {"LF3": {"works_after_history": 3, "grounded_reading_effect": 2},
                         "F5": {"works_after_history": 1, "grounded_reading_effect": 3}}
    contextual_requests = []

    def dispatch(request):
        if request.kind == "contextual":
            contextual_requests.append(request)
            levels = contextual_levels[text_to_id[request.state["candidate_destination"]["text"]]]
        else:
            levels = {"direct_q_fit": 2, **base_levels.get(text_to_id[request.state["destination_page"]["text"]], {})}
        return leveled_outcome(request, levels, mode="mock", returned_model=MOCK_MODEL)

    pairs = [("PR2", pid) for pid in field.candidate_ids_for("PR2")]
    api.build_missing(dispatch, "mock", pairs=pairs)
    rows = api.profiles_for_source("PR2", "mock")
    assert len(rows) == 40 and all(r["status"] == "complete" for r in rows)

    result = offers.build_offers(field, "PR2", [], policy="discovery", dispatch=dispatch, mode="mock",
                                 requested_model="jev-latest")
    assert result["state"] == "offers"
    assert [e["destination_id"] for e in result["shortlist"]] == ["LF3", "F5"]
    assert result["assessed_ids"] == ["LF3", "F5"] and len(contextual_requests) == 2
    assert result["not_assessed_count"] == 38 - 2 and result["base_counts"]["eligible_complete"] == 38
    (offer,) = result["offers"]
    assert offer["destination_id"] == "LF3" and offer["relation_labels"] == ["development"]
    assert offer["base"]["layer"] == "base_pair_profile" and offer["contextual"]["layer"] == "history_conditioned"
    assert [(r["destination_id"], r["stage"]) for r in result["rejected"]] == [("F5", "qualification")]
    assert result["versions"]["atlas_config_id"] == api.active_config("mock")["config_id"]
    assert result["versions"]["pinned_returned_model"] == MOCK_MODEL

    summary = demo.run_demo(dispatch=dispatch, mode="mock", requested_model="jev-latest", field=field)
    assert (isolated / "demos" / "pr2_memory" / "comparison.html").exists()
    assert summary["held_constant"]["shortlist_ids_in_order"] == ["LF3", "F5"]
    assert {k: (c["state"], c["offers"], c["assessed_ids"]) for k, c in summary["conditions"].items()} == {
        k: ("offers", ["LF3"], ["LF3", "F5"]) for k in "abc"}
    assert summary["provider_input_differed_for_every_candidate"] is True
    # condition C has the same (empty) memory as the offers call above: 2 cache hits, so 2 + 4 requests
    assert len(contextual_requests) == 6 and summary["conditions"]["c"]["usage"]["cache_hits"] == 2
