"""Ordered operator composition.

Part 1 is the plan section 4.8 fixture -- a MATHEMATICAL FIXTURE CHECK on three synthetic
pages, separate from any corpus result. Part 2 reads the real atlas (read-only, skipped
when it is absent) and checks the projection and the real E@D / D@E totals against an
independent naive enumerator.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from gibsey_lab.analysis import composition as co
from gibsey_lab.analysis import index_manifest as im
from gibsey_lab.analysis import projection as pj
from gibsey_lab.atlas import api, store
from gibsey_lab.core.identity import version_id


def naive_two_step(M_first, M_second, source=None):
    """Independent enumerator: every (i, k, j) with an edge i->k in the first matrix and
    k->j in the second. Written without reference to the composition module."""
    n = len(M_first)
    walks = []
    for i in range(n):
        if source is not None and i != source:
            continue
        for k in range(n):
            for j in range(n):
                if M_first[i][k] == 1 and M_second[k][j] == 1:
                    walks.append((i, k, j))
    counts = [[0] * n for _ in range(n)]
    for i, _, j in walks:
        counts[i][j] += 1
    return walks, counts


def fixture_manifest(page_ids: list[str], tag: str = "fixture") -> dict:
    """A minimal manifest for synthetic pages (N = len(page_ids)); labeled as a fixture."""
    rows = []
    for i, pid in enumerate(page_ids):
        sha = hashlib.sha256(f"{tag}:{pid}".encode()).hexdigest()
        rows.append({"index": i, "page_id": pid, "version_id": version_id(pid, sha), "sha256": sha})
    return {"schema": "index-manifest/1", "manifest_id": f"man-{tag}", "page_order": rows,
            "operator_order": ["ECHO", "DEVELOP", "CONTRADICT", "BRIDGE"], "projection_rule": "binary-projection-v1",
            "N": len(rows), "O": 4, "label": "mathematical fixture check -- not a corpus measurement"}


# --------------------------------------------------------------------------- plan section 4.8 fixture

A, B, C = 0, 1, 2
FIXTURE = fixture_manifest(["A1", "B1", "C1"], "s48")
# A->B ECHO, A->C DEVELOP, B->C DEVELOP, C->B ECHO
E = [[0, 1, 0], [0, 0, 0], [0, 1, 0]]
D = [[0, 0, 1], [0, 0, 1], [0, 0, 0]]


def test_echo_then_develop_from_a_reaches_exactly_c_via_b():
    result = co.compose(E, D, FIXTURE, source="A1", ops=("ECHO", "DEVELOP"))
    assert result["kind"] == "relation_walk" and "not score-valid" in result["label"]
    assert result["reachable"] == ["C1"] and result["total"] == 1 and result["truncated"] is False
    assert [(w["i"], w["k"], w["j"]) for w in result["witnesses"]] == [(A, B, C)]
    (w,) = result["witnesses"]
    assert w["pages"] == ["A1", "B1", "C1"] and [s["operator"] for s in w["steps"]] == ["ECHO", "DEVELOP"]
    assert result["counts"] == [[0, 0, 1], [0, 0, 0], [0, 0, 1]]  # B has no ECHO out-edge


def test_develop_then_echo_from_a_reaches_exactly_b_via_c():
    result = co.compose(D, E, FIXTURE, source="A1", ops=("DEVELOP", "ECHO"))
    assert result["reachable"] == ["B1"] and result["total"] == 1
    assert [(w["i"], w["k"], w["j"]) for w in result["witnesses"]] == [(A, C, B)]
    assert result["counts"] == [[0, 1, 0], [0, 1, 0], [0, 0, 0]]


def test_operator_order_matters_and_counts_equal_the_naive_enumerator():
    ed = co.compose(E, D, FIXTURE, ops=("ECHO", "DEVELOP"))
    de = co.compose(D, E, FIXTURE, ops=("DEVELOP", "ECHO"))
    assert ed["counts"] != de["counts"]
    for result, first, second in ((ed, E, D), (de, D, E)):
        walks, counts = naive_two_step(first, second)
        assert result["counts"] == counts and result["total"] == len(walks)
        assert [(w["i"], w["k"], w["j"]) for w in result["witnesses"]] == sorted(walks)
    assert co.matmul(E, D) == [[sum(E[i][k] * D[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def test_route_ids_are_stable_and_differ_between_orders():
    first = co.compose(E, D, FIXTURE, source=A, ops=("ECHO", "DEVELOP"))["witnesses"][0]["route_id"]
    again = co.compose(E, D, FIXTURE, source="A1", ops=("ECHO", "DEVELOP"))["witnesses"][0]["route_id"]
    other = co.compose(D, E, FIXTURE, source="A1", ops=("DEVELOP", "ECHO"))["witnesses"][0]["route_id"]
    assert first == again and first.startswith("route_") and first != other
    # a different manifest (other page versions) gives a different route id for the same shape
    other_versions = fixture_manifest(["A1", "B1", "C1"], "s48-edited")
    assert co.compose(E, D, other_versions, source="A1", ops=("ECHO", "DEVELOP"))["witnesses"][0]["route_id"] != first
    # and the assessment ids behind the edges are part of it
    ids_e = [["as-ab" if (i, j) == (A, B) else None for j in range(3)] for i in range(3)]
    ids_d = [["as-bc" if (i, j) == (B, C) else None for j in range(3)] for i in range(3)]
    cited = co.compose(E, D, FIXTURE, source="A1", ops=("ECHO", "DEVELOP"), assessment_ids=(ids_e, ids_d))["witnesses"][0]
    assert [s["assessment_id"] for s in cited["steps"]] == ["as-ab", "as-bc"] and cited["route_id"] != first


def test_cap_truncates_the_display_but_never_the_total():
    dense = [[1, 1, 1], [1, 1, 1], [1, 1, 1]]  # every walk, self-loops included: 27 two-step walks
    full = co.compose(dense, dense, dense_manifest := fixture_manifest(["X1", "Y1", "Z1"], "dense"), ops=("ECHO", "ECHO"))
    walks, counts = naive_two_step(dense, dense)
    assert full["total"] == 27 == len(walks) and full["counts"] == counts and full["truncated"] is False
    assert full["witnesses_shown"] == 27 and full["counts"] == [[3, 3, 3]] * 3

    capped = co.compose(dense, dense, dense_manifest, ops=("ECHO", "ECHO"), cap=5)
    assert capped["total"] == 27 and capped["witnesses_shown"] == 5 and capped["truncated"] is True
    assert capped["witness_cap"] == 5 and capped["counts"] == counts
    assert [(w["i"], w["k"], w["j"]) for w in capped["witnesses"]] == sorted(walks)[:5]  # deterministic prefix

    row = co.compose(dense, dense, dense_manifest, source="Y1", ops=("ECHO", "ECHO"), cap=100)
    assert row["total"] == 9 and row["truncated"] is False and all(w["i"] == 1 for w in row["witnesses"])
    assert row["reachable"] == ["X1", "Y1", "Z1"]
    assert row["cells_nonzero"] == 3 and row["cells_scope"] == "from Y1"  # per-source, not the matrix's 9
    assert full["cells_nonzero"] == 9 and full["cells_scope"] == "whole matrix"

    with pytest.raises(co.CompositionError):
        co.compose(dense, dense, FIXTURE, source="Q9", ops=("ECHO", "ECHO"))
    with pytest.raises(co.CompositionError):
        co.compose(dense, dense, fixture_manifest(["A1", "B1"], "two"), ops=("ECHO", "ECHO"))


def test_compare_orders_on_the_fixture_reports_both_products_and_the_asymmetry():
    projection = {"M": {"ECHO": E, "DEVELOP": D},
                  "assessment_ids": {"ECHO": [[None] * 3 for _ in range(3)], "DEVELOP": [[None] * 3 for _ in range(3)]}}
    report = co.compare_orders(FIXTURE, projection, "ECHO", "DEVELOP", source="A1")
    assert report["totals"] == {"ECHO>DEVELOP": 1, "DEVELOP>ECHO": 1}
    assert report["only_under"] == {"ECHO>DEVELOP": ["C1"], "DEVELOP>ECHO": ["B1"]}
    assert report["cells_differing"] == 4 and report["orders_equal"] is False
    assert {d["page_id"]: d["difference"] for d in report["per_destination"]} == {"B1": -1, "C1": 1}
    with pytest.raises(co.CompositionError):
        co.compare_orders(FIXTURE, projection, "ECHO", "BRIDGE")


# --------------------------------------------------------------------------- real atlas (read-only)

REAL_STORE = Path(store.ASSESSMENTS_PATH)
REAL_CONFIG = Path(api.CONFIG_PATH)
needs_real_atlas = pytest.mark.skipif(
    not (REAL_STORE.exists() and REAL_CONFIG.exists()), reason="real atlas store/config not present"
)


def _independent_included_counts(field, cfg) -> dict[str, int]:
    """A second pass over assessments.jsonl, written without the analysis package:
    latest ok record per live pair whose hashes/config match, floor 2/3 on each dimension."""
    latest: dict[tuple[str, str], dict] = {}
    for line in REAL_STORE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("mode") != "live" or rec.get("status") != "ok":
            continue
        src, dst = rec["source_id"], rec["destination_id"]
        if src not in field.manifest or dst not in field.manifest:
            continue
        if rec["source_sha256"] != field.manifest[src].sha256 or rec["destination_sha256"] != field.manifest[dst].sha256:
            continue
        if rec.get("config_id") != cfg["config_id"] or rec.get("returned_model") != cfg["pinned_returned_model"]:
            continue
        if rec.get("requested_model") != cfg["requested_model"]:
            continue
        if not all(rec["dimensions"].get(d, {}).get("valid") for d in
                   ("echo", "development", "contradiction", "bridge_relation", "direct_q_fit", "redundancy", "missing_context")):
            continue
        latest[(src, dst)] = rec  # file order: the last compatible one wins
    counts = {}
    for op, dim in (("ECHO", "echo"), ("DEVELOP", "development"), ("CONTRADICT", "contradiction"), ("BRIDGE", "bridge_relation")):
        counts[op] = sum(1 for rec in latest.values() if rec["dimensions"][dim]["score_norm"] >= 2 / 3 - 1e-9)
    return counts


@needs_real_atlas
def test_real_atlas_projection_is_fully_assessed_and_matches_an_independent_pass():
    field, cfg = api.current_field(), api.active_config("live")
    if not cfg["frozen"]:
        pytest.skip("live atlas config is not frozen")
    manifest = im.build_manifest(field, cfg)
    assert manifest["N"] == 41 and im.page_ids(manifest)[:9] == ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "F1"]
    projection = pj.project(manifest, field, cfg)
    counts = projection["counts"]
    assert counts["pairs"]["unassessed"] == 0 and counts["pairs"]["complete"] == 1640
    for op in projection["operator_order"]:
        assert counts["per_operator"][op]["unassessed"] == 0 and counts["per_operator"][op]["self"] == 41
        assert sum(map(sum, projection["M"][op])) == counts["included_edges"][op]
        assert all(projection["A"][op][i][j] is not None for i in range(41) for j in range(41) if i != j)
    included = counts["included_edges"]
    assert included["CONTRADICT"] < 60 and included["CONTRADICT"] < included["ECHO"] < included["BRIDGE"]
    assert included == _independent_included_counts(field, cfg)
    assert counts["duplicates_collapsed"] == 0


@needs_real_atlas
def test_real_atlas_compose_totals_equal_the_naive_enumerator():
    field, cfg = api.current_field(), api.active_config("live")
    if not cfg["frozen"]:
        pytest.skip("live atlas config is not frozen")
    manifest = im.build_manifest(field, cfg)
    projection = pj.project(manifest, field, cfg)
    E_real, D_real = projection["M"]["ECHO"], projection["M"]["DEVELOP"]
    report = co.compare_orders(manifest, projection, "ECHO", "DEVELOP")
    ed = report["orders"]["ECHO>DEVELOP"]
    de = report["orders"]["DEVELOP>ECHO"]
    walks_ed, counts_ed = naive_two_step(E_real, D_real)
    walks_de, counts_de = naive_two_step(D_real, E_real)
    assert ed["total"] == len(walks_ed) and ed["counts"] == counts_ed
    assert de["total"] == len(walks_de) and de["counts"] == counts_de
    assert ed["truncated"] is True and ed["witnesses_shown"] == 100
    assert [(w["i"], w["k"], w["j"]) for w in ed["witnesses"]] == sorted(walks_ed)[:100]
    assert report["cells_differing"] == sum(1 for i in range(41) for j in range(41) if counts_ed[i][j] != counts_de[i][j])
    for w in ed["witnesses"]:  # every witness cites the records the projection used
        assert w["steps"][0]["assessment_id"] == projection["assessment_ids"]["ECHO"][w["i"]][w["k"]]
        assert w["steps"][1]["assessment_id"] == projection["assessment_ids"]["DEVELOP"][w["k"]][w["j"]]
