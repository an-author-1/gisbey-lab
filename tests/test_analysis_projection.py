"""Binary projection on SYNTHETIC records: every status code survives, duplicates never
inflate edges, unknown is never zero-filled in A, no policy is applied."""
from __future__ import annotations

import json
import math
from dataclasses import replace

import pytest

from gibsey_lab import scoring
from gibsey_lab.analysis import index_manifest as im
from gibsey_lab.analysis import projection as pj
from gibsey_lab.atlas import api, store
from gibsey_lab.fields import DISCOVERY, INCLUDE_ADJACENT
from test_atlas_support import atlas_env  # noqa: F401

OPS = ("ECHO", "DEVELOP", "CONTRADICT", "BRIDGE")
DIM = {"ECHO": "echo", "DEVELOP": "development", "CONTRADICT": "contradiction", "BRIDGE": "bridge_relation"}


def _probabilities(score: float) -> dict[str, float]:
    lo = min(int(math.floor(score)), 2)
    hi_mass = score - lo
    probs = {str(k): 0.0 for k in range(4)}
    probs[str(lo)] = 1.0 - hi_mass
    probs[str(lo + 1)] = hi_mass
    return probs


def scored(env, scores: dict[tuple[str, str], dict[str, float]], default: float = 2.5):
    """A mock dispatch that answers each dimension with the level requested for that
    pair (by exact text), `default` elsewhere. Never live."""
    by_text = {page.text: pid for pid, page in env.manifest.items()}

    def dispatch(request):
        good = scoring.mock_dispatch(request)
        pair = (by_text[request.state["source_page"]["text"]], by_text[request.state["destination_page"]["text"]])
        levels = scores.get(pair, {})
        answers = {
            q.qid: scoring.validate_answer(q, {"type": "score", "score": levels.get(q.qid, default), "confidence": 0.9,
                                               "probabilities": _probabilities(levels.get(q.qid, default))})
            for q in request.questions
        }
        assert all(a.valid for a in answers.values()), [a.problems for a in answers.values()]
        return replace(good, answers=answers)

    return dispatch


def _project(env):
    field, cfg = env.field(), api.active_config("mock")
    manifest = im.build_manifest(field, cfg)
    return manifest, pj.project(manifest, field, cfg)


def _cell(projection, key, op, src, dst):
    ids = projection["page_ids"]
    return projection[key][op][ids.index(src)][ids.index(dst)]


def test_empty_store_projects_every_off_diagonal_cell_as_unassessed_and_self_on_the_diagonal(atlas_env):
    manifest, p = _project(atlas_env)
    assert p["schema"] == "projection/1" and p["manifest_id"] == manifest["manifest_id"]
    assert p["page_ids"] == list(im.AUTHORED_PAGE_ORDER) and p["policy_applied"] is None
    for op in OPS:
        assert len(p["M"][op]) == 41 and all(len(row) == 41 for row in p["M"][op])
        assert all(v == 0 for row in p["M"][op] for v in row)
        assert all(p["S"][op][i][i] == "self" for i in range(41))
        assert all(p["S"][op][i][j] == "unassessed" for i in range(41) for j in range(41) if i != j)
        assert all(v is None for row in p["A"][op] for v in row)
        assert all(v is None for row in p["assessment_ids"][op] for v in row)
        assert p["counts"]["per_operator"][op] == {"included": 0, "assessed_below_floor": 0, "unassessed": 1640,
                                                   "stale": 0, "failed": 0, "self": 41}
    assert p["counts"]["off_diagonal_cells"] == 1640 and p["counts"]["duplicates_collapsed"] == 0


def test_weak_missing_stale_failed_and_duplicate_records_each_keep_their_status(atlas_env):
    env = atlas_env
    dispatch = scored(env, {
        ("P1", "P2"): {"echo": 1.0, "development": 2.0, "contradiction": 0.0, "bridge_relation": 2.9},
        ("P1", "P3"): {"echo": 2.5},  # other dimensions default 2.5
        ("F1", "F2"): {"echo": 1.9},  # 1.9/3 < 2/3: below floor
        ("LF1", "LF2"): {"echo": 3.0},
    })
    api.build_missing(dispatch, "mock", pairs=[("P1", "P2"), ("P1", "P3"), ("F1", "F2"), ("LF1", "LF2"), ("PR1", "PR2")])
    # A second ok record for P1->P3 (duplicate) and a failed pair PR3->PR4.
    api.build_missing(scored(env, {("P1", "P3"): {"echo": 0.5}}), "mock", pairs=[("P1", "P3")])
    assert api.pair_status("P1", "P3", "mock")["status"] == "complete"  # already complete -> skipped by build
    records, _ = store.read_assessments()
    dup = dict(records[-1])
    dup["assessment_id"], dup["source_id"], dup["destination_id"] = "as-duplicate-p1-p3", "P1", "P3"
    src, dst = env.manifest["P1"], env.manifest["P3"]
    dup["source_sha256"], dup["destination_sha256"] = src.sha256, dst.sha256
    dup["state"] = {"source_page": {"text": src.text}, "destination_page": {"text": dst.text}}
    dup["dimensions"] = json.loads(json.dumps(dup["dimensions"]))
    dup["dimensions"]["echo"]["score"], dup["dimensions"]["echo"]["score_norm"] = 0.5, 0.5 / 3
    dup["dimensions"]["echo"]["probabilities"] = _probabilities(0.5)
    store.append_assessment(dup)

    failing = scoring.ScoreOutcome
    api.build_missing(lambda r: failing("error", "mock", r.requested_model, None, {}, None, 0.0, 1, ["boom"],
                                        r.request_sha256()), "mock", pairs=[("PR3", "PR4")])
    env.edit_page("PR2", "PR2 rewritten after assessment.")  # PR1->PR2 becomes stale

    manifest, p = _project(env)

    # weak score -> assessed_below_floor with M = 0 but the value kept in A
    assert _cell(p, "S", "ECHO", "P1", "P2") == "assessed_below_floor" and _cell(p, "M", "ECHO", "P1", "P2") == 0
    assert _cell(p, "A", "ECHO", "P1", "P2") == pytest.approx(1 / 3)
    assert _cell(p, "S", "DEVELOP", "P1", "P2") == "included" and _cell(p, "M", "DEVELOP", "P1", "P2") == 1
    assert _cell(p, "A", "DEVELOP", "P1", "P2") == pytest.approx(2 / 3)  # exactly level 2 clears the floor
    assert _cell(p, "S", "CONTRADICT", "P1", "P2") == "assessed_below_floor" and _cell(p, "A", "CONTRADICT", "P1", "P2") == 0.0
    assert _cell(p, "S", "BRIDGE", "P1", "P2") == "included"
    assert _cell(p, "S", "ECHO", "F1", "F2") == "assessed_below_floor"
    assert _cell(p, "S", "ECHO", "LF1", "LF2") == "included" and _cell(p, "A", "ECHO", "LF1", "LF2") == pytest.approx(1.0)

    # missing pair -> unassessed, M = 0, A = None (not zero); the reverse direction is separate
    assert _cell(p, "S", "ECHO", "P2", "P1") == "unassessed" and _cell(p, "M", "ECHO", "P2", "P1") == 0
    assert _cell(p, "A", "ECHO", "P2", "P1") is None and _cell(p, "assessment_ids", "ECHO", "P2", "P1") is None

    # stale hash -> stale, no value; failed -> failed, no value
    for op in OPS:
        assert _cell(p, "S", op, "PR1", "PR2") == "stale" and _cell(p, "M", op, "PR1", "PR2") == 0
        assert _cell(p, "A", op, "PR1", "PR2") is None
        assert _cell(p, "S", op, "PR3", "PR4") == "failed" and _cell(p, "A", op, "PR3", "PR4") is None

    # two ok records for one pair -> one edge, latest compatible wins, one duplicate counted
    assert _cell(p, "M", "ECHO", "P1", "P3") == 0 and _cell(p, "S", "ECHO", "P1", "P3") == "assessed_below_floor"
    assert _cell(p, "assessment_ids", "ECHO", "P1", "P3") == "as-duplicate-p1-p3"
    assert _cell(p, "M", "DEVELOP", "P1", "P3") == 1
    assert p["counts"]["duplicates_collapsed"] == 1 and p["counts"]["pairs_with_duplicates"] == 1
    assert sum(p["M"]["DEVELOP"][im.index_of(manifest, "P1")]) == 2  # P2 and P3, not 3

    # self pairs
    assert all(p["S"][op][i][i] == "self" and p["M"][op][i][i] == 0 for op in OPS for i in range(41))

    counts = p["counts"]
    assert counts["pairs"] == {"complete": 4, "stale": 1, "failed": 1, "unassessed": 1634}
    assert counts["per_operator"]["ECHO"] == {"included": 1, "assessed_below_floor": 3, "unassessed": 1634,
                                              "stale": 1, "failed": 1, "self": 41}
    assert counts["included_edges"] == {"ECHO": 1, "DEVELOP": 4, "CONTRADICT": 3, "BRIDGE": 4}
    for op in OPS:
        assert sum(counts["per_operator"][op].values()) == 41 * 41


def test_projection_is_deterministic_and_round_trips_through_the_cache(atlas_env, tmp_path):
    api.build_missing(scoring.mock_dispatch, "mock", pairs=[("P1", "F1"), ("F1", "LF1"), ("LF1", "PR1")])
    manifest, first = _project(atlas_env)
    _, second = _project(atlas_env)
    assert first == second
    cache = tmp_path / "analysis"
    loaded, from_cache = pj.cached_projection(manifest, cache, field=atlas_env.field(), atlas_config=api.active_config("mock"))
    assert from_cache is False and loaded == first
    assert pj.projection_path(manifest["manifest_id"], cache).name == f"projection_{manifest['manifest_id']}.json"
    again, from_cache = pj.cached_projection(manifest, cache)
    assert from_cache is True and again == first
    with pytest.raises(pj.ProjectionError):
        pj.load_projection("man-nope", cache)


def test_a_stale_manifest_is_refused_with_reasons_not_reprojected(atlas_env):
    field, cfg = atlas_env.field(), api.active_config("mock")
    manifest = im.build_manifest(field, cfg)
    api.build_missing(scoring.mock_dispatch, "mock", pairs=[("P1", "P2")])
    with pytest.raises(pj.ProjectionError, match="stale.*records in store changed: 0 -> 1"):
        pj.project(manifest, field, cfg)


def test_eligibility_mask_is_separate_from_the_projection(atlas_env):
    field = atlas_env.field()
    discovery = pj.eligibility_mask(field, DISCOVERY)
    everything = pj.eligibility_mask(field, INCLUDE_ADJACENT)
    ids = list(im.AUTHORED_PAGE_ORDER)
    assert all(everything[i][j] == (1 if i != j else 0) for i in range(41) for j in range(41))
    assert sum(map(sum, everything)) == 1640
    p1, p2, f1, f12, f11 = (ids.index(x) for x in ("P1", "P2", "F1", "F12", "F11"))
    assert discovery[p1][p2] == 0 and discovery[p2][p1] == 0  # authored neighbors excluded
    assert discovery[p1][f1] == 1 and discovery[f12][f11] == 0 and discovery[f12][p1] == 1
    assert discovery[i := ids.index("P8")][ids.index("F1")] == 1  # P8 -> F1 crosses a prefix: not adjacency
    assert sum(map(sum, discovery)) == 1640 - 2 * (7 + 11 + 15 + 4)
    assert all(discovery[i][i] == 0 for i in range(41))
