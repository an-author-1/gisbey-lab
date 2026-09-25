"""Analysis commands: `analysis-manifest`, `analysis-project`, `analysis-compose`.

The lead wires `register_cli` into the main parser. Nothing here dispatches to a
provider or writes to the atlas: outputs go to `data/atlas/index_manifest.json` and
`data/analysis/`. Every composition output is labeled as relation walks in a frozen
projection -- not score-valid navigation, not corpus truth.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..atlas import api as atlas_api
from ..core.identity import OPERATORS
from . import composition
from . import index_manifest as im
from . import projection as pj


def _current(mode: str):
    return atlas_api.current_field(), atlas_api.active_config(mode)


def _load_checked_manifest(path: Path, field, cfg) -> dict | None:
    try:
        manifest = im.load_manifest(path)
    except im.ManifestError as e:
        print(str(e), file=sys.stderr)
        return None
    check = im.check_manifest(manifest, field, cfg)
    if check["stale"]:
        print(f"manifest {manifest['manifest_id']} at {path} is STALE; current would be "
              f"{check['current_manifest_id']}. Not rebuilding silently -- run `gibsey analysis-manifest`.",
              file=sys.stderr)
        for reason in check["reasons"]:
            print(f"  stale: {reason}", file=sys.stderr)
        return None
    return manifest


def cmd_analysis_manifest(args: argparse.Namespace) -> int:
    field, cfg = _current(args.mode)
    try:
        manifest = im.build_manifest(field, cfg)
    except im.ManifestError as e:
        print(str(e), file=sys.stderr)
        return 1
    path = Path(args.path)
    previous = None
    if path.exists():
        try:
            previous = im.load_manifest(path)
        except im.ManifestError:
            previous = None
    if previous is not None and previous["manifest_id"] == manifest["manifest_id"]:
        print(f"manifest {manifest['manifest_id']} unchanged at {path}")
    else:
        im.write_manifest(manifest, path)
        if previous is None:
            print(f"wrote manifest {manifest['manifest_id']} to {path}")
        else:
            report = im.check_manifest(previous, field, cfg)
            print(f"replaced manifest {previous['manifest_id']} with {manifest['manifest_id']} at {path}")
            for reason in report["reasons"]:
                print(f"  changed: {reason}")
    snap = manifest["snapshot"]
    print(f"N={manifest['N']} pages in authored order ({manifest['page_order'][0]['page_id']} .. "
          f"{manifest['page_order'][-1]['page_id']}), O={manifest['O']} operators {manifest['operator_order']}")
    print(f"atlas {snap['atlas_config_id']} [{snap['atlas_mode']}] rubric={snap['rubric_version']} "
          f"pinned={snap['pinned_returned_model']}; complete pairs {snap['complete_pairs']}; "
          f"records in store {snap['records_in_store']}")
    print(f"assessment set {snap['assessment_set_sha256'][:12]}  corpus {snap['corpus_sha256'][:12]}  "
          f"rule {manifest['projection_rule']} floor {manifest['support_floor']:.4f}")
    return 0


def cmd_analysis_project(args: argparse.Namespace) -> int:
    field, cfg = _current(args.mode)
    manifest = _load_checked_manifest(Path(args.manifest), field, cfg)
    if manifest is None:
        return 1
    try:
        projection, cached = pj.cached_projection(manifest, args.out_dir, field=field, atlas_config=cfg)
    except pj.ProjectionError as e:
        print(str(e), file=sys.stderr)
        return 1
    path = pj.projection_path(manifest["manifest_id"], args.out_dir)
    print(f"projection {manifest['manifest_id']} ({'cached' if cached else 'computed'}) at {path}")
    counts = projection["counts"]
    print(f"{counts['off_diagonal_cells']} off-diagonal cells: " + ", ".join(
        f"{s} {c}" for s, c in counts["pairs"].items()))
    print(f"duplicates collapsed: {counts['duplicates_collapsed']} (pairs with duplicates: {counts['pairs_with_duplicates']})")
    ops = [args.operator] if args.operator else projection["operator_order"]
    for op in ops:
        per = counts["per_operator"][op]
        print(f"  {op:10s} dimension={projection['dimension_of'][op]:16s} " + "  ".join(
            f"{code} {per[code]}" for code in pj.STATUS_CODES if code != "self"))
    print("M is a binary projection under the support floor; 0 is not a negative verdict. No policy applied.")
    return 0


def _parse_ops(text: str) -> tuple[str, str]:
    ops = tuple(part.strip().upper() for part in text.split(","))
    if len(ops) != 2 or any(op not in OPERATORS for op in ops):
        raise argparse.ArgumentTypeError(f"--ops must be two of {OPERATORS} separated by a comma, got {text!r}")
    return ops


def compose_output_path(manifest_id: str, ops: tuple[str, str], source: str | None, root: Path | str) -> Path:
    name = f"compose_{manifest_id}_{ops[0]}-{ops[1]}" + (f"_{source}" if source else "") + ".json"
    return Path(root) / name


def cmd_analysis_compose(args: argparse.Namespace) -> int:
    field, cfg = _current(args.mode)
    manifest = _load_checked_manifest(Path(args.manifest), field, cfg)
    if manifest is None:
        return 1
    try:
        projection, _ = pj.cached_projection(manifest, args.out_dir, field=field, atlas_config=cfg)
        ops = args.ops
        result = composition.compare_orders(manifest, projection, ops[0], ops[1], args.source, cap=args.cap)
    except (pj.ProjectionError, composition.CompositionError, im.ManifestError) as e:
        print(str(e), file=sys.stderr)
        return 1
    path = compose_output_path(manifest["manifest_id"], ops, args.source, args.out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    first = f"{ops[0]}>{ops[1]}"
    second = f"{ops[1]}>{ops[0]}"
    where = f"from {args.source}" if args.source else "over all sources"
    print(f"{composition.LABEL}")
    print(f"manifest {manifest['manifest_id']}  {where}  -> {path}")
    for key in (first, second):
        walk = result["orders"][key]
        cells = (f"destinations reached from {args.source} {walk['cells_nonzero']}" if args.source
                 else f"nonzero cells {walk['cells_nonzero']}")
        print(f"  {key:22s} total {walk['total']:6d} two-step walks {where}; {cells}; "
              f"witnesses shown {walk['witnesses_shown']}" + (" (TRUNCATED)" if walk["truncated"] else ""))
    print(f"  cells differing between orders: {result['cells_differing']} "
          f"({'orders agree' if result['orders_equal'] else 'order matters'})")
    if args.source:
        for key in (first, second):
            only = result["only_under"][key]
            print(f"  reachable only under {key}: {', '.join(only) if only else '-'}")
    return 0


def register_cli(subparsers) -> None:
    p = subparsers.add_parser("analysis-manifest", help="build the index manifest (authored page order + atlas snapshot)")
    p.add_argument("--mode", choices=atlas_api.MODES, default="live")
    p.add_argument("--path", default=str(im.MANIFEST_PATH))
    p.set_defaults(func=cmd_analysis_manifest)

    p = subparsers.add_parser("analysis-project", help="binary projection M/S/A of the atlas under the index manifest")
    p.add_argument("--operator", choices=OPERATORS, default=None)
    p.add_argument("--mode", choices=atlas_api.MODES, default="live")
    p.add_argument("--manifest", default=str(im.MANIFEST_PATH))
    p.add_argument("--out-dir", default=str(pj.ANALYSIS_DIR))
    p.set_defaults(func=cmd_analysis_project)

    p = subparsers.add_parser("analysis-compose", help="two-step operator composition (relation walks, both orders)")
    p.add_argument("--ops", type=_parse_ops, required=True, help="e.g. ECHO,DEVELOP")
    p.add_argument("--source", default=None, help="restrict witnesses/totals to this source page, e.g. P1")
    p.add_argument("--cap", type=int, default=composition.DEFAULT_CAP, help="max witnesses displayed per order")
    p.add_argument("--mode", choices=atlas_api.MODES, default="live")
    p.add_argument("--manifest", default=str(im.MANIFEST_PATH))
    p.add_argument("--out-dir", default=str(pj.ANALYSIS_DIR))
    p.set_defaults(func=cmd_analysis_compose)
