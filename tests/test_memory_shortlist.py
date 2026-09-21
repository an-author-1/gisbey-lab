import copy
import random

from gibsey_lab.memory import shortlist as sl
from test_memory_helpers import make_field, make_rows

SOURCE = "PR2"


def _build(field, scores, policy="discovery", **kw):
    rows = make_rows(field, SOURCE, scores, **{k: kw.pop(k) for k in ("statuses", "default_status") if k in kw})
    return sl.build_shortlist(rows, field.eligible_candidate_ids(SOURCE, policy), page_order=field.all_ids(), **kw), rows


def test_reasons_recorded_per_relation_and_order_is_by_best_support():
    field = make_field()
    result, _ = _build(field, {
        "LF2": {"contradiction": 1.0}, "PR5": {"development": 0.8, "echo": 0.7}, "P1": {"bridge_relation": 0.67},
        "LF4": {"echo": 0.62},  # below the 2/3 floor (cleared v1's 0.5): supports nothing
    })
    assert result["policy_version"] == "shortlist-v2" and sl.RELATION_FLOOR == 2 / 3
    assert [e["destination_id"] for e in result["entries"]] == ["LF2", "PR5", "P1"]
    pr5 = result["entries"][1]
    assert pr5["reasons"] == [
        {"relation": "echo", "score_norm": 0.7, "floor": sl.RELATION_FLOOR, "rank_in_relation": 1},
        {"relation": "development", "score_norm": 0.8, "floor": sl.RELATION_FLOOR, "rank_in_relation": 1},
    ]
    assert pr5["best_relation"] == "development" and pr5["relation_labels"] == ["echo", "development"]
    assert set(pr5["base"]) == set(sl.ALL_DIMENSIONS)
    assert all(e["reasons"] for e in result["entries"])
    assert result["thresholds"]["status"] == "provisional application policy"


def test_top_two_per_relation_with_near_misses_explained():
    field = make_field()
    result, _ = _build(field, {"LF1": {"echo": 0.9}, "LF2": {"echo": 0.8}, "LF3": {"echo": 0.7}})
    assert [e["destination_id"] for e in result["entries"]] == ["LF1", "LF2"]
    (missed,) = result["excluded"]
    assert missed["destination_id"] == "LF3" and "not in the top 2 for echo" in missed["excluded_reasons"][0]


def test_gates_and_redundancy_are_reasons_not_silent_drops():
    field = make_field()
    result, _ = _build(field, {
        "LF1": {"development": 0.9, "direct_q_fit": 0.2},
        "LF2": {"development": 0.9, "missing_context": 1.0},
        "LF3": {"development": 0.9, "redundancy": 1.0},
        "LF4": {"echo": 0.9, "redundancy": 1.0},
        "LF5": {"echo": 0.7, "contradiction": 0.8, "redundancy": 0.9},
    })
    ids = [e["destination_id"] for e in result["entries"]]
    assert ids == ["LF4", "LF5"]
    reasons = {x["destination_id"]: x["excluded_reasons"] for x in result["excluded"]}
    assert "direct_q_fit" in reasons["LF1"][0] and "missing_context" in reasons["LF2"][0]
    assert "only echo may support a redundant page" in reasons["LF3"][0]
    lf4, lf5 = result["entries"]
    assert "entered via echo" in lf4["notes"][0]
    assert [r["relation"] for r in lf5["reasons"]] == ["echo"]          # contradiction support refused...
    assert "contradiction" in reasons["LF5"][0]                          # ...and the refusal is recorded
    assert lf5["relation_labels"] == ["echo", "contradiction"]           # labels report the base profile as it is


def test_only_complete_rows_are_eligible_and_policy_exclusions_are_counted():
    field = make_field()
    scores = {pid: {"development": 0.9} for pid in ("PR1", "PR3", "LF1", "LF2", "LF3")}
    result, _ = _build(field, scores, statuses={"LF1": "stale", "LF2": "failed", "LF3": "unassessed"})
    assert result["entries"] == []  # PR1/PR3 are authored neighbors (discovery), the rest are not complete
    assert result["counts"]["ineligible_incomplete"] == 3 and result["counts"]["ineligible_policy"] == 2
    assert result["ineligible_incomplete_ids"] == ["LF1", "LF2", "LF3"]
    adjacent, _ = _build(field, scores, policy="include-adjacent", statuses={"LF1": "stale", "LF2": "failed", "LF3": "unassessed"})
    assert [e["destination_id"] for e in adjacent["entries"]] == ["PR1", "PR3"]
    assert all(e["is_authored_neighbor"] for e in adjacent["entries"])  # neighbors are not banned, only policy-gated


def test_weak_atlas_gives_empty_shortlist():
    field = make_field()
    result, _ = _build(field, {})
    assert result["entries"] == [] and result["excluded"] == []
    assert result["counts"]["below_all_relation_floors"] == result["counts"]["complete_eligible"] == 15


def test_cap_and_tie_break_by_page_order():
    field = make_field()
    scores = {pid: {dim: 0.9 for dim in sl.RELATION_DIMENSIONS} for pid in field.candidate_ids_for(SOURCE)}
    default, _ = _build(field, scores)
    assert [e["destination_id"] for e in default["entries"]] == ["LF1", "LF2"]  # identical scores: field page order
    distinct = {}
    for i, pid in enumerate(["LF1", "LF2", "LF3", "LF4", "LF5", "LF6", "P1", "P2", "P3", "P4", "PR4", "PR5"]):
        distinct[pid] = {sl.RELATION_DIMENSIONS[i % 4]: 0.9 - i * 0.01}
    capped, _ = _build(field, distinct, per_relation_top=3)
    assert len(capped["entries"]) == sl.SHORTLIST_CAP == 8
    assert [e["position"] for e in capped["entries"]] == list(range(1, 9))
    cut = [x for x in capped["excluded"] if "cut by the shortlist cap" in x["excluded_reasons"][-1]]
    assert len(cut) == 4


def test_deterministic_under_row_order_and_repeat():
    field = make_field()
    scores = {"LF2": {"contradiction": 0.7}, "LF3": {"contradiction": 0.7}, "PR6": {"echo": 0.9, "bridge_relation": 0.7},
              "P2": {"bridge_relation": 0.7}, "P3": {"development": 0.68}}
    first, rows = _build(field, scores)
    for seed in range(5):
        shuffled = copy.deepcopy(rows)
        random.Random(seed).shuffle(shuffled)
        again = sl.build_shortlist(shuffled, field.eligible_candidate_ids(SOURCE, "discovery"), page_order=field.all_ids())
        assert again == first
    assert [e["destination_id"] for e in first["entries"]] == ["PR6", "LF2", "LF3", "P2", "P3"]


def test_relation_labels_never_include_weak_dimensions():
    # 0.62 is the pilot's intended-weak pair: it cleared v1's 0.5 floor and must not clear v2's.
    # An expected score of exactly 2.0 of 3 (the rubric's first definite level) must clear it.
    row = make_rows(make_field(), SOURCE, {"LF1": {"echo": 0.62, "development": 2.0 / 3, "contradiction": 0.5}})
    lf1 = next(r for r in row if r["destination_id"] == "LF1")
    assert sl.relation_labels(lf1) == ["development"]
    assert sl.clears(2.0 / 3, sl.RELATION_FLOOR) and not sl.clears(1.99 / 3, sl.RELATION_FLOOR)
