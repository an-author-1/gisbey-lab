"""The three analysis commands on a synthetic atlas, writing only under tmp_path."""
from __future__ import annotations

import argparse
import json

from gibsey_lab import scoring
from gibsey_lab.analysis import cli as analysis_cli
from gibsey_lab.analysis import index_manifest as im
from gibsey_lab.atlas import api
from test_atlas_support import atlas_env  # noqa: F401


def _run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    analysis_cli.register_cli(parser.add_subparsers(dest="command", required=True))
    args = parser.parse_args(argv)
    return args.func(args)


def test_manifest_project_and_compose_commands(atlas_env, tmp_path, capsys):
    api.build_missing(scoring.mock_dispatch, "mock", pairs=[("P1", "P2"), ("P2", "P3"), ("P1", "P3"), ("P3", "P1")])
    manifest_path = tmp_path / "atlas" / "index_manifest.json"
    out_dir = tmp_path / "analysis"

    assert _run(["analysis-manifest", "--mode", "mock", "--path", str(manifest_path)]) == 0
    out = capsys.readouterr().out
    manifest = im.load_manifest(manifest_path)
    assert f"wrote manifest {manifest['manifest_id']}" in out and "P1 .. PR5" in out
    assert _run(["analysis-manifest", "--mode", "mock", "--path", str(manifest_path)]) == 0
    assert "unchanged" in capsys.readouterr().out

    assert _run(["analysis-project", "--mode", "mock", "--manifest", str(manifest_path), "--out-dir", str(out_dir),
                 "--operator", "ECHO"]) == 0
    out = capsys.readouterr().out
    assert "computed" in out and "ECHO" in out and "DEVELOP" not in out.split("dimension=")[0]
    assert (out_dir / f"projection_{manifest['manifest_id']}.json").exists()
    assert _run(["analysis-project", "--mode", "mock", "--manifest", str(manifest_path), "--out-dir", str(out_dir)]) == 0
    assert "cached" in capsys.readouterr().out

    assert _run(["analysis-compose", "--mode", "mock", "--manifest", str(manifest_path), "--out-dir", str(out_dir),
                 "--ops", "echo,develop", "--source", "P1", "--cap", "3"]) == 0
    out = capsys.readouterr().out
    assert "relation walks in a frozen projection" in out and "ECHO>DEVELOP" in out and "DEVELOP>ECHO" in out
    assert "destinations reached from P1" in out and "nonzero cells" not in out
    path = out_dir / f"compose_{manifest['manifest_id']}_ECHO-DEVELOP_P1.json"
    written = json.loads(path.read_text())
    assert written["kind"] == "relation_walk" and "not score-valid navigation" in written["label"]
    assert written["source"]["page_id"] == "P1" and set(written["orders"]) == {"ECHO>DEVELOP", "DEVELOP>ECHO"}
    assert all(o["witness_cap"] == 3 for o in written["orders"].values())
    for walk in written["orders"].values():  # per-source figures, scoped like the totals
        assert walk["cells_scope"] == "from P1"
        assert walk["cells_nonzero"] == sum(1 for c in walk["counts"][0] if c > 0) == len(walk["destinations"])
        assert walk["total"] == sum(walk["counts"][0])

    assert _run(["analysis-compose", "--mode", "mock", "--manifest", str(manifest_path), "--out-dir", str(out_dir),
                 "--ops", "BRIDGE,CONTRADICT"]) == 0
    out = capsys.readouterr().out
    assert "nonzero cells" in out and "destinations reached" not in out
    whole = json.loads((out_dir / f"compose_{manifest['manifest_id']}_BRIDGE-CONTRADICT.json").read_text())
    assert all(o["cells_scope"] == "whole matrix" for o in whole["orders"].values())


def test_commands_refuse_a_stale_manifest_instead_of_rebuilding(atlas_env, tmp_path, capsys):
    manifest_path = tmp_path / "index_manifest.json"
    assert _run(["analysis-manifest", "--mode", "mock", "--path", str(manifest_path)]) == 0
    before = manifest_path.read_text()
    api.build_missing(scoring.mock_dispatch, "mock", pairs=[("LF1", "LF2")])
    capsys.readouterr()
    for argv in (["analysis-project"], ["analysis-compose", "--ops", "ECHO,DEVELOP"]):
        rc = _run(argv + ["--mode", "mock", "--manifest", str(manifest_path), "--out-dir", str(tmp_path / "a")])
        err = capsys.readouterr().err
        assert rc == 1 and "STALE" in err and "records in store changed: 0 -> 1" in err
    assert manifest_path.read_text() == before and not (tmp_path / "a").exists()

    assert _run(["analysis-manifest", "--mode", "mock", "--path", str(manifest_path)]) == 0
    out = capsys.readouterr().out
    assert "replaced manifest" in out and "changed: records in store changed: 0 -> 1" in out
