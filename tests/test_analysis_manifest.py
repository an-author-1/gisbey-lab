"""Index manifest: authored order, stable ids, coordinate round trips, staleness."""
from __future__ import annotations

import json

import pytest

from gibsey_lab import scoring
from gibsey_lab.analysis import index_manifest as im
from gibsey_lab.atlas import api
from gibsey_lab.core.identity import parse_version_id
from gibsey_lab.fields import FULL_41, Field
from test_atlas_support import atlas_env  # noqa: F401

AUTHORED = (
    [f"P{i}" for i in range(1, 9)] + [f"F{i}" for i in range(1, 13)]
    + [f"LF{i}" for i in range(1, 17)] + [f"PR{i}" for i in range(1, 6)]
)


def _build(atlas_env):
    return im.build_manifest(atlas_env.field(), api.active_config("mock"))


def test_manifest_has_41_rows_in_authored_order_and_4_operators(atlas_env):
    m = _build(atlas_env)
    assert m["schema"] == "index-manifest/1" and m["N"] == 41 and m["O"] == 4
    assert [r["page_id"] for r in m["page_order"]] == AUTHORED == list(im.AUTHORED_PAGE_ORDER)
    assert [r["index"] for r in m["page_order"]] == list(range(41))
    assert m["operator_order"] == ["ECHO", "DEVELOP", "CONTRADICT", "BRIDGE"]
    assert m["dimension_of"] == {"ECHO": "echo", "DEVELOP": "development", "CONTRADICT": "contradiction",
                                 "BRIDGE": "bridge_relation"}
    assert m["projection_rule"] == "binary-projection-v1" and m["support_floor"] == pytest.approx(2 / 3)
    assert m["collapse_rule"] == "latest compatible ok record per pair"
    for row in m["page_order"]:
        page, sha12 = parse_version_id(row["version_id"])
        assert page == row["page_id"] and row["sha256"].startswith(sha12)
        assert row["sha256"] == atlas_env.manifest[row["page_id"]].sha256
    assert set(m["snapshot"]) >= {"atlas_config_id", "rubric_version", "pinned_returned_model",
                                  "assessment_set_sha256", "records_in_store", "corpus_sha256"}


def test_field_all_ids_order_is_not_the_manifest_order(atlas_env):
    """`Field.all_ids()` sorts prefixes alphabetically (F, LF, P, PR); the manifest is
    authored order (P, F, LF, PR). The first ids differ, so the two must never be mixed."""
    field = atlas_env.field()
    m = _build(atlas_env)
    manifest_ids = im.page_ids(m)
    assert field.all_ids()[0] == "F1" and manifest_ids[0] == "P1"
    assert field.all_ids() != manifest_ids and sorted(field.all_ids()) == sorted(manifest_ids)


def test_manifest_id_is_stable_across_builds_and_follows_the_snapshot(atlas_env):
    first, second = _build(atlas_env), _build(atlas_env)
    assert first["manifest_id"] == second["manifest_id"] and first == second
    assert first["snapshot"]["records_in_store"] == 0 and first["snapshot"]["complete_pairs"] == 0

    api.build_missing(scoring.mock_dispatch, "mock", pairs=[("P1", "P2")])
    third = _build(atlas_env)
    assert third["manifest_id"] != first["manifest_id"]
    assert third["snapshot"]["records_in_store"] == 1 and third["snapshot"]["complete_pairs"] == 1
    assert third["snapshot"]["assessment_set_sha256"] != first["snapshot"]["assessment_set_sha256"]
    assert third["snapshot"]["corpus_sha256"] == first["snapshot"]["corpus_sha256"]  # texts unchanged
    assert [r["version_id"] for r in third["page_order"]] == [r["version_id"] for r in first["page_order"]]


def test_a_changed_page_hash_changes_the_manifest(atlas_env):
    before = _build(atlas_env)
    atlas_env.edit_page("LF3", "LF3 has been rewritten entirely.")
    after = _build(atlas_env)
    assert after["manifest_id"] != before["manifest_id"]
    assert after["snapshot"]["corpus_sha256"] != before["snapshot"]["corpus_sha256"]
    changed = [(a["page_id"], a["version_id"], b["version_id"])
               for a, b in zip(before["page_order"], after["page_order"]) if a["version_id"] != b["version_id"]]
    assert [c[0] for c in changed] == ["LF3"] and changed[0][1] != changed[0][2]
    assert im.page_ids(after) == im.page_ids(before)  # order is authored, unaffected by content


def test_a_field_that_is_not_the_authored_41_is_refused(atlas_env):
    field = atlas_env.field()
    partial = Field(id=FULL_41, label="partial", manifest={k: v for k, v in field.manifest.items() if k != "PR5"})
    with pytest.raises(im.ManifestError, match="missing \\['PR5'\\]"):
        im.build_manifest(partial, api.active_config("mock"))


def test_offset_and_decode_round_trip_every_coordinate_and_reject_out_of_bounds(atlas_env):
    m = _build(atlas_env)
    n, o_count = m["N"], m["O"]
    seen = set()
    for i in range(n):
        for j in range(n):
            for o in range(o_count):
                off = im.offset(m, i, j, o)
                assert off == ((i * n) + j) * o_count + o
                assert im.decode(m, off) == (i, j, o)
                seen.add(off)
    assert seen == set(range(n * n * o_count)) and len(seen) == 6724
    assert im.offset(m, 0, 0, 0) == 0 and im.offset(m, 40, 40, 3) == 6723
    for bad in [(-1, 0, 0), (41, 0, 0), (0, 41, 0), (0, 0, 4), (0, 0, -1), (True, 0, 0)]:
        with pytest.raises(im.ManifestError, match="out of bounds"):
            im.offset(m, *bad)
    for bad in [-1, 6724, 10 ** 6, False]:
        with pytest.raises(im.ManifestError, match="out of bounds"):
            im.decode(m, bad)


def test_index_lookups(atlas_env):
    m = _build(atlas_env)
    assert im.index_of(m, "P1") == 0 and im.index_of(m, "F1") == 8 and im.index_of(m, "LF1") == 20
    assert im.index_of(m, "PR5") == 40 and im.operator_index(m, "BRIDGE") == 3
    with pytest.raises(im.ManifestError):
        im.index_of(m, "ZZ9")
    with pytest.raises(im.ManifestError):
        im.operator_index(m, "REPEAT")


def test_write_load_and_check_report_stale_reasons_instead_of_rebuilding(atlas_env, tmp_path):
    field, cfg = atlas_env.field(), api.active_config("mock")
    m = im.build_manifest(field, cfg)
    path = im.write_manifest(m, tmp_path / "index_manifest.json")
    loaded = im.load_manifest(path)
    assert loaded == m == json.loads(path.read_text())
    fresh = im.check_manifest(loaded, field, cfg)
    assert fresh == {"manifest_id": m["manifest_id"], "current_manifest_id": m["manifest_id"], "stale": False,
                     "reasons": []}

    api.build_missing(scoring.mock_dispatch, "mock", pairs=[("P1", "P2"), ("F3", "LF2")])
    atlas_env.edit_page("PR2", "PR2 rewritten.")
    report = im.check_manifest(loaded, atlas_env.field(), cfg)
    assert report["stale"] is True and report["current_manifest_id"] != m["manifest_id"]
    text = "\n".join(report["reasons"])
    assert "PR2 text changed" in text and "records in store changed: 0 -> 2" in text
    assert "set of complete assessments changed" in text
    assert im.load_manifest(path) == m  # the file on disk was not touched by the check

    with pytest.raises(im.ManifestError, match="no index manifest"):
        im.load_manifest(tmp_path / "missing.json")
    (tmp_path / "bad.json").write_text('{"schema": "other/1"}')
    with pytest.raises(im.ManifestError, match="not an index-manifest/1"):
        im.load_manifest(tmp_path / "bad.json")
