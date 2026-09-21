"""Atlas commands: `atlas-inspect`, `atlas-coverage`, `atlas-build`, `atlas-resume`.

The lead wires `register_cli` into the main parser. Output is always a short summary.
A live build gets its dispatch from `LIVE_DISPATCH_FACTORY`, which the lead points at
the ledgered live gateway; by default it refuses, so nothing in this package can make a
provider call on its own. Mock output is always labeled MOCK.
"""
from __future__ import annotations

import argparse
import sys
from typing import Callable

from ..scoring import Dispatch, mock_dispatch
from . import api, choice_history
from .rubrics import DIMENSIONS

PROGRESS_EVERY = 25
MAX_HISTORY_ROWS = 12


def _live_dispatch_not_wired() -> Dispatch:
    raise RuntimeError(
        "live dispatch is lead-wired: set gibsey_lab.atlas.cli.LIVE_DISPATCH_FACTORY to a callable "
        "returning the ledgered live dispatch. No live call was made."
    )


LIVE_DISPATCH_FACTORY: Callable[[], Dispatch] = _live_dispatch_not_wired


def _mode_label(mode: str) -> str:
    return "LIVE" if mode == "live" else "MOCK (not a literary judgment, never counted as live)"


def _config_line(cfg: dict) -> str:
    frozen = "frozen" if cfg["frozen"] else "NOT FROZEN (pilot)"
    return (f"config {cfg['config_id']} [{frozen}] rubric={cfg['rubric_version']} "
            f"requested={cfg['requested_model']} pinned={cfg['pinned_returned_model']}")


def _fmt(value) -> str:
    return "-" if value is None else f"{value:.2f}"


def cmd_atlas_inspect(args: argparse.Namespace) -> int:
    try:
        status = api.pair_status(args.source, args.destination, mode=args.mode)
    except api.AtlasError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"{args.source} -> {args.destination}   [{_mode_label(args.mode)}]   (directed; the reverse is a separate entry)")
    neighbor = f"yes ({status['neighbor_relation']} page of the source)" if status["is_authored_neighbor"] else "no"
    print(f"status: {status['status'].upper()}   authored neighbor: {neighbor}   records for this pair: {status['record_count']}")
    print(_config_line(api.active_config(args.mode)))

    record = status["record"]
    print("\nLayer 1 -- base pair profile (independent Score assessment of this pair)")
    if record is not None:
        for dim in DIMENSIONS:
            d = record["dimensions"][dim]
            print(f"  {dim:16s} score {_fmt(d['score'])} / {d['max_level']}   confidence {_fmt(d['confidence'])}")
        usage = record.get("usage") or {}
        print(f"  provenance: {record['assessment_id']} at {record['at']} job {record['job_id']}")
        print(f"    requested {record['requested_model']} -> returned {record['returned_model']}; "
              f"attempts {record['attempts']}; {record['elapsed_seconds']:.2f}s; "
              f"input tokens {usage.get('input_tokens', 'unreported')}")
        print(f"    source sha256 {record['source_sha256'][:12]}  destination sha256 {record['destination_sha256'][:12]}  "
              f"request sha256 {record['request_sha256'][:12]}")
    else:
        print("  no compatible assessment -- this is NOT a score of zero.")
        for reason in status["stale_reasons"]:
            print(f"  stale: {reason}")
        for error in status["last_errors"]:
            print(f"  last failure: {error[:160]}")

    rows = choice_history.choice_rows_for_pair(args.source, args.destination)
    print(f"\nLayer 2 -- field-relative Choice history ({len(rows)} saved request(s); read-only)")
    print("  Probabilities below are relative to the candidates competing in each request.")
    print("  They are not pair scores and never feed the profile above.")
    for row in rows[-MAX_HISTORY_ROWS:]:
        live = "live" if row["live"] else "mock"
        if row["row_kind"] == "reverse_operator_typing":
            detail = f"reverse operator typing -> {row['selected_operator']}"
        else:
            picked = "SELECTED" if row["selected"] else f"request chose {row['request_choice']}"
            none = "+NONE" if row["had_none_option"] else "no NONE"
            detail = (f"{row['operator'] or '-':10s} p={_fmt(row['probability'])} among {row['candidate_count']} ({none}); {picked}")
        print(f"  {row['run_id'][:16]} {live} {row['field']}/{row['policy']}/{row['criteria_version']} "
              f"{detail} [{row['returned_model']}]")
    if len(rows) > MAX_HISTORY_ROWS:
        print(f"  ... {len(rows) - MAX_HISTORY_ROWS} earlier request(s) not shown")
    return 0


def cmd_atlas_coverage(args: argparse.Namespace) -> int:
    cov = api.coverage(args.mode)
    counts = cov["counts"]
    print(f"Atlas coverage [{_mode_label(args.mode)}] over {cov['total_pairs']} directed pairs (authored neighbors included)")
    print(_config_line(cov["config"]))
    print("  " + "   ".join(f"{s}: {counts[s]}" for s in api.STATUSES))
    print(f"  returned models among complete pairs: {', '.join(cov['returned_models']) or 'none'}"
          + ("   ** MIXED -- not one atlas **" if cov["mixed_returned_models"] else ""))
    others = [m for m in cov["returned_models_seen_in_store"] if m not in cov["returned_models"]]
    if others:
        print(f"  other returned models in the store (not pooled): {', '.join(others)}")
    if cov["corrupt_lines_skipped"]:
        print(f"  corrupt store lines skipped: {cov['corrupt_lines_skipped']}")
    incomplete = {s: c for s, c in cov["per_source"].items() if c["complete"] != sum(c.values())}
    print(f"  sources fully complete: {len(cov['per_source']) - len(incomplete)} of {len(cov['per_source'])}")
    if incomplete and len(incomplete) < len(cov["per_source"]):
        cells = [f"{s} {c['complete']}/{sum(c.values())}" for s, c in incomplete.items()]
        print("  incomplete sources (complete/total):")
        for i in range(0, len(cells), 8):
            print("    " + "   ".join(cells[i:i + 8]))
    if args.mode == "live":
        verdict = "COMPLETE live atlas" if cov["is_complete_live_atlas"] else "NOT a complete live atlas"
        print(f"  {verdict}.")
    else:
        print("  Mock coverage says nothing about live coverage.")
    return 0


def _parse_pairs(text: str | None) -> list[tuple[str, str]] | None:
    if not text:
        return None
    pairs = []
    for chunk in text.split(","):
        source, sep, destination = chunk.strip().partition(":")
        if not sep or not source or not destination:
            raise api.AtlasError(f"bad pair {chunk!r}; expected SRC:DST")
        pairs.append((source.strip(), destination.strip()))
    return pairs


def _run_build(mode: str, *, limit, pairs, concurrency, requested_model, pinned_model) -> int:
    try:
        parsed_pairs = _parse_pairs(pairs)
        dispatch = mock_dispatch if mode == "mock" else LIVE_DISPATCH_FACTORY()
    except (api.AtlasError, RuntimeError) as e:
        print(str(e), file=sys.stderr)
        return 1

    def progress(snapshot: dict) -> None:
        if snapshot["attempted"] % PROGRESS_EVERY == 0:
            print(f"  ... {snapshot['attempted']}/{snapshot['of']} attempted "
                  f"(ok {snapshot['ok']}, invalid {snapshot['invalid']}, error {snapshot['error']})", file=sys.stderr)

    print(f"Atlas build [{_mode_label(mode)}]")
    try:
        summary = api.build_missing(
            dispatch, mode, limit=limit, pairs=parsed_pairs, concurrency=concurrency,
            requested_model=requested_model, pinned_returned_model=pinned_model, on_progress=progress,
        )
    except api.AtlasError as e:
        print(f"build refused: {e}", file=sys.stderr)
        return 1
    print(f"  job {summary['job_id']}   config {summary['config_id']}" + ("" if summary["frozen"] else "   [config NOT frozen]"))
    print(f"  targeted {summary['targeted']}   skipped (already complete) {summary['skipped_complete']}   "
          f"attempted {summary['attempted']}: ok {summary['ok']}, invalid {summary['invalid']}, error {summary['error']}")
    if summary["model_mismatch"]:
        print(f"  returned-model mismatches (recorded, not pooled): {summary['model_mismatch']}")
    print(f"  stopped: {summary['stopped_reason'] or 'all targeted work done'}   remaining (not complete): {summary['remaining']}")
    if summary["remaining"]:
        print(f"  resume with: {summary['resume_command']}")
    return 0 if summary["stopped_reason"] in (None, "limit") else 2


def cmd_atlas_build(args: argparse.Namespace) -> int:
    return _run_build(
        "live" if args.live else "mock", limit=args.limit, pairs=args.pairs, concurrency=args.concurrency,
        requested_model=args.requested_model, pinned_model=args.pinned_model,
    )


def cmd_atlas_resume(args: argparse.Namespace) -> int:
    last = api.last_job()
    if last is None:
        print("no atlas job has recorded anything yet; start one with `gibsey atlas-build --mock|--live`", file=sys.stderr)
        return 1
    print(f"Resuming in the mode of the last job ({last['job_id']}): {last['mode']}")
    return _run_build(last["mode"], limit=args.limit, pairs=None, concurrency=args.concurrency,
                      requested_model=None, pinned_model=None)


def register_cli(subparsers) -> None:
    p = subparsers.add_parser("atlas-inspect", help="one directed pair: status, seven dimensions, provenance, Choice history")
    p.add_argument("source")
    p.add_argument("destination")
    p.add_argument("--mode", choices=api.MODES, default="live")
    p.set_defaults(func=cmd_atlas_inspect)

    p = subparsers.add_parser("atlas-coverage", help="complete/stale/failed/unassessed counts over all 1,640 pairs")
    p.add_argument("--mode", choices=api.MODES, default="live")
    p.set_defaults(func=cmd_atlas_coverage)

    p = subparsers.add_parser("atlas-build", help="assess pairs that are not complete under the active config")
    which = p.add_mutually_exclusive_group(required=True)
    which.add_argument("--mock", action="store_true")
    which.add_argument("--live", action="store_true")
    p.add_argument("--limit", type=int, default=None, help="dispatch at most N requests")
    p.add_argument("--pairs", default=None, help="only these directed pairs, e.g. F12:P8,P8:F12")
    p.add_argument("--concurrency", type=int, default=api.MAX_CONCURRENCY, choices=range(1, api.MAX_CONCURRENCY + 1))
    p.add_argument("--requested-model", default=None)
    p.add_argument("--pinned-model", default=None, help="pilot only: pin a returned model before the config is frozen")
    p.set_defaults(func=cmd_atlas_build)

    p = subparsers.add_parser("atlas-resume", help="continue the last build (same mode); complete pairs are skipped")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--concurrency", type=int, default=api.MAX_CONCURRENCY, choices=range(1, api.MAX_CONCURRENCY + 1))
    p.set_defaults(func=cmd_atlas_resume)
