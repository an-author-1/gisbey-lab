"""CLI for the memory layer. The lead wires `register_cli` into gibsey_lab.cli.

`memory-packet`, `operator-options` and `operator-coverage` are read-only: they read the
base atlas through atlas.api and never dispatch, whatever --mode says (the mode only picks
which atlas view, live or mock, is read). `offers` and `pr2-demo` need a dispatch: `--mock` uses
`scoring.mock_dispatch`; `--live` asks LIVE_DISPATCH_FACTORY, which the lead replaces with
the ledgered live gateway. The factory takes no arguments and returns either a Dispatch
or a `(dispatch, requested_model)` tuple. This module never reads credentials itself.
"""
from __future__ import annotations

import argparse
import json
import sys

from .. import session_log
from ..config import DEFAULT_MODEL
from ..fields import DEFAULT_FIELD, DEFAULT_POLICY, KNOWN_FIELDS, KNOWN_POLICIES, load_field
from ..scoring import mock_dispatch
from . import demo, offers, operator_options
from .packet import build_memory_packet, encounters_from_events, summarize


def _live_dispatch_not_wired():
    raise RuntimeError("live dispatch is lead-wired: set gibsey_lab.memory.cli.LIVE_DISPATCH_FACTORY "
                       "to a factory returning the ledgered live dispatch. No live call was made.")


LIVE_DISPATCH_FACTORY = _live_dispatch_not_wired


def _read_events() -> list[dict]:
    # Prefer the reader's seq-stamping reader when present, so legacy lines get their true
    # line index even if a garbled line was skipped; read-only either way.
    reader = getattr(session_log, "read_events_with_seq", session_log.read_events)
    return reader(session_log.DEFAULT_LOG_PATH)


def _dispatch_for(args: argparse.Namespace):
    if args.live:
        made = LIVE_DISPATCH_FACTORY()
        dispatch, model = made if isinstance(made, tuple) else (made, None)
        return dispatch, "live", args.model or model or DEFAULT_MODEL
    return mock_dispatch, "mock", args.model or DEFAULT_MODEL


def cmd_memory_packet(args: argparse.Namespace) -> int:
    field = load_field(args.field)
    events = _read_events()
    page_id = args.page
    if page_id is None:
        trace = encounters_from_events(events, field)
        if not trace:
            print("no page encounters in the session log; pass --page ID", file=sys.stderr)
            return 1
        page_id = trace[-1]["page_id"]
    packet = build_memory_packet(field, page_id, events, candidate_policy=args.policy,
                                 log_path=session_log.DEFAULT_LOG_PATH)
    print(json.dumps(summarize(packet), indent=2, ensure_ascii=False))
    return 0


def cmd_offers(args: argparse.Namespace) -> int:
    try:
        dispatch, mode, model = _dispatch_for(args)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    field = load_field(args.field)
    events = _read_events()
    result = offers.build_offers(field, args.page, events, policy=args.policy, dispatch=dispatch, mode=mode,
                                 requested_model=model, reuse_cache=not args.no_cache)
    print(f"{result['offer_set_id']}  state={result['state']}  mode={mode}  shortlist={len(result['shortlist'])}  "
          f"assessed={len(result['assessed_ids'])}  not_assessed={result['not_assessed_count']}  "
          f"cache_hits={result['usage']['cache_hits']}")
    for offer in result["offers"]:
        works = offer["contextual"]["answers"]["works_after_history"]["score"]
        print(f"  {offer['rank']}. {offer['destination_id']:5s} labels={','.join(offer['relation_labels']) or '-'} "
              f"works_after_history={works:.2f}{' (cached)' if offer['from_cache'] else ''}")
    for error in result["errors"][:5]:
        print(f"  error: {error}", file=sys.stderr)
    return 0 if result["state"] != "error" else 1


def cmd_pr2_demo(args: argparse.Namespace) -> int:
    try:
        dispatch, mode, model = _dispatch_for(args)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    summary = demo.run_demo(dispatch=dispatch, mode=mode, requested_model=model, policy=args.policy)
    print(f"{demo.BANNER}\nmode={mode} model={model} shortlist={summary['held_constant']['shortlist_ids_in_order']}")
    for key, condition in summary["conditions"].items():
        print(f"  {condition['condition']} {'>'.join(condition['declared_path']):14s} state={condition['state']} "
              f"offers={condition['offers']}")
    print(f"provider input differed for every candidate: {summary['provider_input_differed_for_every_candidate']}")
    print(f"wrote {summary['demo_dir']}/comparison.html")
    return 0


def cmd_operator_options(args: argparse.Namespace) -> int:
    field = load_field(args.field)
    try:
        result = operator_options.operator_options(field, args.page, args.operator, policy=args.policy, mode=args.mode)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    counts = result["counts"]
    print(f"{result['option_set_id']}  {result['page_id']} {result['operator']}  state={result['state']}  "
          f"policy={result['policy']}  mode={result['mode']}  eligible={counts['eligible']} usable={counts['usable']} "
          f"supported={counts['supported']} exploratory_shown={counts['exploratory_shown']} unusable={counts['unusable']}")
    for option in result["options"]:
        fit = option["operator_fit"]
        confidence = "-" if fit["confidence"] is None else f"{fit['confidence']:.2f}"
        print(f"  {option['rank']}. {option['destination_id']:5s} {option['tier_label']:36s} "
              f"{fit['dimension']}={fit['score_norm']:.2f} conf={confidence}"
              f"{'  cautions=' + ','.join(option['cautions']) if option['cautions'] else ''}")
    for error in result["errors"]:
        print(f"  error: {error}", file=sys.stderr)
    return 0 if result["state"] != "atlas_unavailable" else 1


def _one_read_provider(page_id: str, mode: str):
    """Read the page's 40 profile rows once and serve them to all four operators; a read
    failure is re-raised inside operator_options so it is reported as atlas_unavailable."""
    try:
        rows = operator_options._default_profiles_provider(page_id, mode)
    except Exception as e:  # noqa: BLE001
        error = e

        def failing(source_id: str, mode: str) -> list[dict]:
            raise error

        return failing
    return lambda source_id, mode: rows


def cmd_operator_coverage(args: argparse.Namespace) -> int:
    """Every page x operator from the existing atlas. Exit 1 if any combination with at
    least MIN_SHOWN eligible pages shows fewer than MIN_SHOWN options."""
    field = load_field(args.field)
    need = operator_options.MIN_SHOWN
    failures = 0
    lines = {op: {"ok": 0, "filled": 0, "short": []} for op in operator_options.OPERATOR_DIMENSIONS}
    for page_id in field.all_ids():
        provider = _one_read_provider(page_id, args.mode)
        for op, line in lines.items():
            result = operator_options.operator_options(field, page_id, op, policy=args.policy, mode=args.mode,
                                                       profiles_provider=provider)
            shown, eligible = len(result["options"]), result["counts"]["eligible"]
            if shown >= need:
                line["ok"] += 1
                line["filled"] += 1 if result["counts"]["exploratory_shown"] else 0
                continue
            why = result["state_detail"] or result["state"]
            statuses = sorted({u["status"] for u in result["unusable"]})
            line["short"].append(f"{page_id}: {shown} shown, {eligible} eligible, {why}"
                                 f"{' (unusable: ' + ','.join(statuses) + ')' if statuses else ''}")
            if eligible >= need:
                failures += 1
    pages = len(field.all_ids())
    print(f"operator coverage  field={field.id} policy={args.policy} mode={args.mode} pages={pages} "
          f"policy_version={operator_options.OPTIONS_POLICY_VERSION}")
    for op, line in lines.items():
        print(f"  {op:10s} {line['ok']}/{pages} pages show >={need}; {line['filled']} needed exploratory fill; "
              f"{len(line['short'])} show <{need}{': ' + '; '.join(line['short']) if line['short'] else ''}")
    print(f"result: {'FAIL' if failures else 'OK'} ({failures} combination(s) with >={need} eligible pages show <{need})")
    return 1 if failures else 0


def _add_mode(p: argparse.ArgumentParser, *, required: bool) -> None:
    group = p.add_mutually_exclusive_group(required=required)
    group.add_argument("--mock", action="store_true", help="deterministic offline dispatch (default)")
    group.add_argument("--live", action="store_true", help="lead-wired live dispatch")
    p.add_argument("--model", default=None)
    p.add_argument("--policy", choices=KNOWN_POLICIES, default=DEFAULT_POLICY)


def register_cli(subparsers) -> None:
    p = subparsers.add_parser("memory-packet", help="summarize the memory packet for the real session log (read-only)")
    p.add_argument("--page", default=None)
    p.add_argument("--field", choices=KNOWN_FIELDS, default=DEFAULT_FIELD)
    p.add_argument("--policy", choices=KNOWN_POLICIES, default=DEFAULT_POLICY)
    p.set_defaults(func=cmd_memory_packet)

    p = subparsers.add_parser("offers", help="build up to three history-conditioned route offers for PAGE")
    p.add_argument("page")
    p.add_argument("--field", choices=KNOWN_FIELDS, default=DEFAULT_FIELD)
    p.add_argument("--no-cache", action="store_true")
    _add_mode(p, required=False)
    p.set_defaults(func=cmd_offers)

    p = subparsers.add_parser("pr2-demo", help="PR2 arrival-history demonstration (fixtures only)")
    _add_mode(p, required=True)
    p.set_defaults(func=cmd_pr2_demo)

    p = subparsers.add_parser("operator-options", help="ranked destinations for PAGE under OPERATOR from the base atlas")
    p.add_argument("page")
    p.add_argument("operator")
    p.add_argument("--field", choices=KNOWN_FIELDS, default=DEFAULT_FIELD)
    p.add_argument("--policy", choices=KNOWN_POLICIES, default=DEFAULT_POLICY)
    p.add_argument("--mode", choices=("live", "mock"), default="live", help="which atlas view to read; never dispatches")
    p.set_defaults(func=cmd_operator_options)

    p = subparsers.add_parser("operator-coverage", help="check every page x operator shows at least three options")
    p.add_argument("--field", choices=KNOWN_FIELDS, default=DEFAULT_FIELD)
    p.add_argument("--policy", choices=KNOWN_POLICIES, default=DEFAULT_POLICY)
    p.add_argument("--mode", choices=("live", "mock"), default="live", help="which atlas view to read; never dispatches")
    p.set_defaults(func=cmd_operator_coverage)
