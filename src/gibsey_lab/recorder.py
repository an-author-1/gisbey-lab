from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .context import ContextPacket
from .results import ChoiceResult
from .validate import ValidatedOutcome

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs"


def _git_revision() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def record_run(
    *,
    packet: ContextPacket,
    result: ChoiceResult | None,
    outcome: ValidatedOutcome | None,
    error: str | None,
    retries: int,
    corpus_hashes: dict[str, str],
    runs_dir: Path = RUNS_DIR,
) -> Path:
    stamp = _utc_stamp()
    mode = "error" if result is None else ("mock" if not result.live else "live")
    run_id = f"{stamp}_{packet.case_id}_{mode}"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    input_record = {
        "run_id": run_id,
        "case_id": packet.case_id,
        "working_index": packet.working_index,
        "source_id": packet.source_id,
        "active_id": packet.active_id,
        "criterion": packet.criterion,
        "option_order": packet.option_order,
        "options": packet.options,
        "reader_state": packet.reader_state,
        "git_revision": _git_revision(),
        "corpus_hashes": corpus_hashes,
    }
    (run_dir / "input.json").write_text(json.dumps(input_record, indent=2, ensure_ascii=False) + "\n")

    response_record = {
        "live": result.live if result else None,
        "requested_model": result.requested_model if result else None,
        "returned_model": result.returned_model if result else None,
        "choice": result.choice if result else None,
        "confidence": result.confidence if result else None,
        "probabilities": result.probabilities if result else None,
        "usage": result.usage if result else None,
        "elapsed_seconds": result.elapsed_seconds if result else None,
        "retries": retries,
        "error": error,
    }
    (run_dir / "response.json").write_text(json.dumps(response_record, indent=2, ensure_ascii=False) + "\n")

    outcome_record = outcome.to_dict() if outcome else None
    (run_dir / "result.json").write_text(json.dumps(outcome_record, indent=2, ensure_ascii=False) + "\n")

    (run_dir / "report.md").write_text(_render_report(packet, result, outcome, error, mode, run_id))

    review_record = {
        "correspondence": None,
        "reading_effect": None,
        "grounding_score": None,  # 0 absent, 1 plausible but thin, 2 convincing
        "effect_score": None,  # 0 absent, 1 limited, 2 substantial
        "decision": "undecided",
    }
    (run_dir / "review.json").write_text(json.dumps(review_record, indent=2, ensure_ascii=False) + "\n")
    (run_dir / "review.md").write_text(_render_review_template(run_id))

    return run_dir


def _render_report(packet: ContextPacket, result, outcome, error, mode, run_id) -> str:
    lines = [f"# Run {run_id}", "", f"**Case:** {packet.case_id}  ", f"**Mode:** {mode.upper()}  "]

    if error:
        lines += ["", "## Outcome: ERROR", "", "```", error, "```"]
        return "\n".join(lines) + "\n"

    lines += [f"**Model requested:** {result.requested_model}  ", f"**Model returned:** {result.returned_model}  ", ""]

    active_label = packet.active_id or packet.source_id
    active_text = packet.active_text or f"(full page {packet.source_id} — see input.json for exact text)"
    lines += ["## Source / active passage", "", f"**{active_label}:**", "", "> " + active_text.replace("\n", "\n> "), ""]

    if outcome is None:
        lines += ["## Outcome: no validated result"]
        return "\n".join(lines) + "\n"

    if outcome.is_abstention:
        lines += ["## Outcome: ABSTENTION (NONE)", "", "Jev found no eligible option supporting a defensible correspondence.", ""]
    else:
        lines += [
            "## Selected destination",
            "",
            f"**{outcome.selected_id}:**",
            "",
            "> " + outcome.selected_text.replace("\n", "\n> "),
            "",
        ]

    lines += ["## Confidence and distribution", "", f"- confidence: {outcome.confidence}", "- probabilities:"]
    for k in packet.option_order:
        lines.append(f"  - {k}: {outcome.probabilities.get(k)}")
    lines += ["", f"- elapsed: {result.elapsed_seconds:.3f}s", f"- usage: {result.usage}", ""]
    lines += ["## Human review", "", "See `review.md` — pending."]
    return "\n".join(lines) + "\n"


def _render_review_template(run_id: str) -> str:
    return f"""# Human review — {run_id}

Status: **pending**

- **What is the correspondence?**
  _(pending)_

- **What does reading these passages together change?**
  _(pending)_

- **Grounding** (0 absent, 1 plausible but thin, 2 convincing): _(pending)_
- **Reading effect** (0 absent, 1 limited, 2 substantial): _(pending)_
- **Decision** (accept / reject / undecided): undecided

Fill in with:

    gibsey review {run_id} --correspondence "..." --change "..." --grounding N --effect N --decision accept|reject|undecided
"""
