from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import cases, state
from .config import load_config
from .context import CaseError, assemble
from .corpus import corpus_hashes, load_manifest, validate_manifest
from .recorder import RUNS_DIR
from .reviewing import ReviewError, update_review
from .runner import run_case
from .sentence_map import SentenceMapError, approve, load_reviewed_map, propose_sentence_map, save_map


def cmd_validate_corpus(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    problems = validate_manifest(manifest)
    hashes = corpus_hashes(manifest)

    print(f"Loaded {len(manifest)} pages.")
    for pid in sorted(hashes, key=lambda p: (p[0], manifest[p].order)):
        flag = " EMPTY" if manifest[pid].is_empty else ""
        print(f"  {pid:5s} sha256={hashes[pid][:12]}...{flag}")

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
    else:
        print("\nNo problems found.")

    manifest_path = Path("data") / "corpus_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "pages": {
                    pid: {"path": str(manifest[pid].path.relative_to(Path.cwd())), "sha256": h, "order": manifest[pid].order}
                    for pid, h in hashes.items()
                },
                "problems": problems,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"\nWrote {manifest_path}")
    return 1 if problems else 0


def cmd_propose_sentence_map(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    page = manifest.get(args.page_id)
    if page is None:
        print(f"unknown page id: {args.page_id}", file=sys.stderr)
        return 1
    sm = propose_sentence_map(page)
    path = save_map(sm)
    print(f"status: {sm.status}")
    print(f"wrote {path}")
    for sid, text in sm.sentences.items():
        print(f"  {sid}: {text}")
    return 0


def cmd_review_sentence_map(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    page = manifest.get(args.page_id)
    if page is None:
        print(f"unknown page id: {args.page_id}", file=sys.stderr)
        return 1

    if args.approve:
        try:
            sm = approve(page)
        except SentenceMapError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"approved. status: {sm.status}")
        return 0

    from .sentence_map import load_map

    sm = load_map(args.page_id)
    if sm is None:
        print(f"no mapping proposed yet for {args.page_id}; run propose-sentence-map first")
        return 1
    print(f"status: {sm.status}")
    for sid, text in sm.sentences.items():
        print(f"  {sid}: {text}")
    print("\nApprove with: gibsey review-sentence-map", args.page_id, "--approve")
    return 0


def cmd_run_case(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    sentence_map = load_reviewed_map(manifest["F12"]) if "F12" in manifest and not manifest["F12"].is_empty else None

    try:
        packet = assemble(args.case, manifest, sentence_map)
    except CaseError as e:
        print(f"case error: {e}", file=sys.stderr)
        return 1

    cfg = load_config()
    if not args.mock and not cfg.has_live_credentials:
        print("error: --mock not set and TYPESAFE_API_KEY is not configured", file=sys.stderr)
        return 1

    outcome = run_case(packet, cfg, mock=args.mock, corpus_hashes=corpus_hashes(manifest))
    print(f"run_dir: {outcome['run_dir']}")
    if not outcome["ok"]:
        print(f"error: {outcome['error']}", file=sys.stderr)
        return 1

    v = outcome["outcome"]
    if v.is_abstention:
        print("outcome: ABSTENTION (NONE)")
    else:
        print(f"outcome: {v.selected_id} (confidence={v.confidence})")
    return 0


def cmd_show_run(args: argparse.Namespace) -> int:
    run_dir = RUNS_DIR / args.run_id if not Path(args.run_id).exists() else Path(args.run_id)
    report = run_dir / "report.md"
    if not report.exists():
        print(f"no report at {report}", file=sys.stderr)
        return 1
    print(report.read_text())
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    run_dir = RUNS_DIR / args.run_id if not Path(args.run_id).exists() else Path(args.run_id)
    try:
        review = update_review(
            run_dir,
            correspondence=args.correspondence,
            reading_effect=args.change,
            grounding_score=args.grounding,
            effect_score=args.effect,
            decision=args.decision,
        )
    except ReviewError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"updated {run_dir / 'review.json'}")
    print(json.dumps(review, indent=2, ensure_ascii=False))
    return 0


def cmd_propose(args: argparse.Namespace) -> int:
    run_dir = RUNS_DIR / args.run_id if not Path(args.run_id).exists() else Path(args.run_id)
    try:
        proposal_id = state.propose(run_dir)
    except state.StateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(proposal_id)
    return 0


def cmd_accept(args: argparse.Namespace) -> int:
    try:
        bond_id = state.accept(args.proposal_id)
    except state.StateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(bond_id)
    return 0


def cmd_follow(args: argparse.Namespace) -> int:
    try:
        s = state.follow(args.bond_id)
    except state.StateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(s, indent=2, ensure_ascii=False))
    return 0


def cmd_preserve(args: argparse.Namespace) -> int:
    try:
        entry_id = state.preserve(args.bond_id)
    except state.StateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(entry_id)
    return 0


def cmd_reader_state(args: argparse.Namespace) -> int:
    print(json.dumps(state.reader_state(), indent=2, ensure_ascii=False))
    return 0


def cmd_serve_reader(args: argparse.Namespace) -> int:
    from .reader.server import run as run_reader_server

    run_reader_server(port=args.port, open_browser=not args.no_open)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gibsey")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate-corpus").set_defaults(func=cmd_validate_corpus)

    p = sub.add_parser("propose-sentence-map")
    p.add_argument("page_id")
    p.set_defaults(func=cmd_propose_sentence_map)

    p = sub.add_parser("review-sentence-map")
    p.add_argument("page_id")
    p.add_argument("--approve", action="store_true")
    p.set_defaults(func=cmd_review_sentence_map)

    p = sub.add_parser("run-case")
    p.add_argument("case", choices=cases.KNOWN_CASE_IDS)
    p.add_argument("--mock", action="store_true")
    p.set_defaults(func=cmd_run_case)

    p = sub.add_parser("show-run")
    p.add_argument("run_id")
    p.set_defaults(func=cmd_show_run)

    p = sub.add_parser("review")
    p.add_argument("run_id")
    p.add_argument("--correspondence")
    p.add_argument("--change")
    p.add_argument("--grounding", type=int, choices=[0, 1, 2])
    p.add_argument("--effect", type=int, choices=[0, 1, 2])
    p.add_argument("--decision", choices=["accept", "reject", "undecided"])
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("propose")
    p.add_argument("run_id")
    p.set_defaults(func=cmd_propose)

    p = sub.add_parser("accept")
    p.add_argument("proposal_id")
    p.set_defaults(func=cmd_accept)

    p = sub.add_parser("follow")
    p.add_argument("bond_id")
    p.set_defaults(func=cmd_follow)

    p = sub.add_parser("preserve")
    p.add_argument("bond_id")
    p.set_defaults(func=cmd_preserve)

    sub.add_parser("reader-state").set_defaults(func=cmd_reader_state)

    p = sub.add_parser("serve-reader")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true", help="don't open a browser tab automatically")
    p.set_defaults(func=cmd_serve_reader)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
