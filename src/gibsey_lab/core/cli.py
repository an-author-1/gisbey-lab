"""CLI for Core v0.3 sessions: inspect, replay and export journeys. Read-only except
`core-start` / `core-execute`, which are the same operations the reader performs (for
scripted or provider-free demonstrations). Nothing here calls a model."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import journal, replay
from .core import Core, CoreError


def _core() -> Core:
    from ..session_log import DEFAULT_LOG_PATH
    from ..state import DEFAULT_DATA_DIR

    try:
        from . import projectors  # mirrors committed actions into the legacy reader stores
    except ImportError:
        return Core()
    return Core(projectors=[projectors.mirror_to_legacy_stores(DEFAULT_DATA_DIR, DEFAULT_LOG_PATH)])


def cmd_sessions(args: argparse.Namespace) -> int:
    core = _core()
    for sid in journal.list_sessions(core.core_dir):
        s = core.resume_session(sid)
        print(f"{sid}  rev={s['revision']}  encounters={len(s['encounters'])}  at={s['active_version']}  paused={s['paused']}")
    return 0


def cmd_journey(args: argparse.Namespace) -> int:
    core = _core()
    try:
        s = core.resume_session(args.session_id)
    except CoreError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"session {args.session_id}  revision {s['revision']}  {len(s['encounters'])} encounter(s)  paused={s['paused']}")
    for h in s["encounters"]:
        ret = f"  return: distance {h['return_index_distance']}, {h['intervening_encounters']} intervening" if "return_index_distance" in h else ""
        via = h["via"] if h["via"] != "Q" else f"Q via bond {h['bond_version_id']} (request {h['request_id']})"
        print(f"  #{h['encounter_index']}  {h['version_id']}  {via}{ret}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    core = _core()
    result = replay.replay(args.session_id, core)
    s, d = result["state_replay"], result["decision_replay"]
    print(f"state replay: {'OK' if s['ok'] else 'MISMATCH'} ({s['events']} events, final revision {s['final_revision']}, "
          f"{len(s['per_event_mismatches'])} per-event mismatches)")
    print(f"decision replay: {'OK' if d['ok'] else 'DRIFT'} ({d['offer_sets']} offer sets recomputed, {len(d['drift'])} drifted)")
    print("provider calls: 0")
    if args.export:
        path = replay.export_bundle(args.session_id, core, Path(args.export))
        print(f"bundle: {path}")
    return 0 if result["ok"] else 1


def cmd_start(args: argparse.Namespace) -> int:
    s = _core().start_session(args.page, session_id=args.session_id)
    print(json.dumps({k: s[k] for k in ("session_id", "revision", "active_version")}))
    return 0


def cmd_options(args: argparse.Namespace) -> int:
    o = _core().resolve_options(args.session_id, args.operator.upper(), policy=args.policy)
    print(f"offer set {o['offer_set_id']} at revision {o['revision']} from {o['source_version']} ({'reused' if o.get('reused') else 'new'})")
    for b in o["bonds"]:
        fit = b["operator_fit"]
        print(f"  {b['bond_version_id']}  -> {b['destination_version']}  {b['tier']:11s} fit {fit.get('score_norm'):.2f} conf {fit.get('confidence'):.2f}")
        print(f"      offered: «{b['wording']}»")
    return 0


def cmd_execute(args: argparse.Namespace) -> int:
    try:
        r = _core().execute_action(args.session_id, offer_set_id=args.offer_set_id, bond_version_id=args.bond_version_id,
                                   expected_revision=args.expected_revision, request_id=args.request_id)
    except CoreError as e:
        print(f"rejected: {e.code}: {e}", file=sys.stderr)
        return 1
    print(json.dumps({k: r[k] for k in ("status", "duplicate", "to_page", "to_version", "revision_after", "encounter_index")}))
    return 0


def register_cli(sub) -> None:
    sub.add_parser("core-sessions", help="list Core sessions").set_defaults(func=cmd_sessions)
    p = sub.add_parser("core-journey", help="ordered encounters of a session (read-only)")
    p.add_argument("session_id")
    p.set_defaults(func=cmd_journey)
    p = sub.add_parser("core-replay", help="provider-disabled state + decision replay")
    p.add_argument("session_id")
    p.add_argument("--export", help="also write a self-contained journey bundle to this directory")
    p.set_defaults(func=cmd_replay)
    p = sub.add_parser("core-start", help="start a session at a page (same operation as the reader)")
    p.add_argument("page")
    p.add_argument("--session-id")
    p.set_defaults(func=cmd_start)
    p = sub.add_parser("core-options", help="resolve and persist the offer set for an operator")
    p.add_argument("session_id")
    p.add_argument("operator")
    p.add_argument("--policy", default="discovery")
    p.set_defaults(func=cmd_options)
    p = sub.add_parser("core-execute", help="execute an offered bond (validated, deduplicated, atomic)")
    p.add_argument("session_id")
    p.add_argument("offer_set_id")
    p.add_argument("bond_version_id")
    p.add_argument("--expected-revision", type=int, required=True)
    p.add_argument("--request-id", required=True)
    p.set_defaults(func=cmd_execute)
