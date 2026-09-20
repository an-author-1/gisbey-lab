"""Shared helper for updating a run's review.json. Used by both the CLI `review`
command and the reader app, so there is one code path for this optional, human-only
record -- never fed into any Jev request."""
from __future__ import annotations

import json
from pathlib import Path


class ReviewError(Exception):
    pass


def update_review(
    run_dir: Path,
    *,
    correspondence: str | None = None,
    reading_effect: str | None = None,
    grounding_score: int | None = None,
    effect_score: int | None = None,
    decision: str | None = None,
) -> dict:
    review_path = Path(run_dir) / "review.json"
    if not review_path.exists():
        raise ReviewError(f"no review.json at {review_path}")
    review = json.loads(review_path.read_text())
    if correspondence is not None:
        review["correspondence"] = correspondence
    if reading_effect is not None:
        review["reading_effect"] = reading_effect
    if grounding_score is not None:
        review["grounding_score"] = grounding_score
    if effect_score is not None:
        review["effect_score"] = effect_score
    if decision is not None:
        review["decision"] = decision
    review_path.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n")
    return review
